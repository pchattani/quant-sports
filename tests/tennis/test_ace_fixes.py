"""Code/docs agreement fixes (docs/tennis/MODELS.md section 14): the indoor flag in the site's prices, the
tour's own blend in the backtest's fallback, ranking points from canon only, the fits in the page signatures,
the cold-cache refit budget and the derived next-season Slams key."""
from __future__ import annotations

import importlib.util
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from oddsmarkets.tennis import canon
from oddsmarkets.tennis.models import _io
from oddsmarkets.tennis.models import _points
from oddsmarkets.tennis.models import backtest as BT
from oddsmarkets.tennis.models import predict as PR
from oddsmarkets.tennis.models import serve_return as SR

ROOT = Path(__file__).resolve().parents[2]

SR_MODEL = {"version": SR.VERSION, "through": "2026-09-30",
            "base": {"mu": 1.0, "clay": -0.1, "grass": 0.2, "indoor": 0.4, "bo5": -0.2, "k_hold": 0.0, "k_spw": 0.0,
                     "level": {"250": 0.05}, "new_s": 0.0, "new_r": 0.0},
            "players": {"a": {"all": {"s": 0.3, "r": 0.1}, "hard": {"s": 0.35, "r": 0.1}},
                        "b": {"all": {"s": -0.1, "r": 0.0}, "hard": {"s": -0.1, "r": 0.05}}}}


# ── 3. indoor: the site's price is the one the backtest scores ──────────────────────────────────────────────

def test_predict_passes_indoor_like_the_backtest():
    ctx = PR.Context("atp", date(2026, 10, 1), sr_model=SR_MODEL, sr_mod=SR, elo_fn=lambda *a: 0.6)
    row = {"p1": "a", "p2": "b", "surface": "hard", "best_of": 3, "level": "250", "final_set_rule": "tb7"}
    out_in, out_out = PR.predict_many(ctx, [dict(row, indoor=True), dict(row, indoor=False)], with_dist=False)
    # exactly what backtest.predictions computes for the same match
    for out, flag in ((out_in, True), (out_out, False)):
        h1 = SR.hold_prob(SR_MODEL, "a", "b", "hard", "250", 3, flag)
        h2 = SR.hold_prob(SR_MODEL, "b", "a", "hard", "250", 3, flag)
        assert out["p_srv_sr"] == pytest.approx([SR.point_prob_from_hold(h1), SR.point_prob_from_hold(h2)], abs=1e-12)
    assert out_in["p_srv_sr"][0] > out_out["p_srv_sr"][0]          # the fitted indoor term (+0.4) is applied
    assert out_in["sr_p"] != pytest.approx(out_out["sr_p"], abs=1e-6)
    p = PR.predict("atp", "a", "b", "hard", level="250", ctx=ctx, indoor=True, with_dist=False)
    assert p["p_srv_sr"] == pytest.approx(out_in["p_srv_sr"])


def test_site_predictions_carry_the_match_indoor_flag(monkeypatch):
    from oddsmarkets.tennis.analytics import matches as MT
    seen = []

    def fake_many(ctx, rows, with_dist=False, shift=True):
        seen.extend(rows)
        return [{"p1_win": 0.5} for _ in rows]
    monkeypatch.setattr(PR, "predict_many", fake_many)

    class TD:
        today = date(2026, 10, 1)
        sr_skipped: set = set()

        def elo_pre(self, m):
            return 0.5

        def context(self, cp, exact_elo=None):
            return None
    ms = [{"id": "m1", "p1": "a", "p2": "b", "date": "2026-02-10", "status": "done", "surface": "hard", "indoor": True},
          {"id": "m2", "p1": "a", "p2": "b", "date": "2026-10-02", "status": "upcoming", "surface": "clay"}]
    MT.predictions(TD(), ms)
    by = {(r["date"]): r for r in seen}
    assert by["2026-02-10"]["indoor"] is True and by["2026-10-02"]["indoor"] is False


# ── 4. backtest.evaluate: the tour's own blend when a year has nothing earlier ──────────────────────────────

def _row(year, flip=False):
    return {"year": year, "elo": 0.7, "sr": 0.6, "flip": flip, "rank_x": 0.1, "books": {}, "level": "250"}


@pytest.mark.parametrize("tour", ["atp", "wta"])
def test_evaluate_fallback_is_the_tours_own_blend(tour):
    ev = BT.evaluate([_row(2010), _row(2010, True)], [2010], tour=tour)
    own = PR.blend_params(tour)
    w = ev["blend_by_year"]["2010"]
    assert not w["fitted"]
    assert w["w_elo"] == pytest.approx(round(own["w_elo"], 4)) and w["w_sr"] == pytest.approx(round(own["w_sr"], 4))
    r = ev["_scored"][0]
    assert r["_model"] == pytest.approx(float(PR.blend(0.7, 0.6, own["w_elo"], own["w_sr"])))


def test_evaluate_wta_differs_from_the_atp_fallback():
    a = BT.evaluate([_row(2010)], [2010], tour="atp")["blend_by_year"]["2010"]
    w = BT.evaluate([_row(2010)], [2010], tour="wta")["blend_by_year"]["2010"]
    assert (a["w_elo"], a["w_sr"]) != (w["w_elo"], w["w_sr"])
    f = _io.read_json(_io.FITTED / "predict_wta.json")
    assert w["w_elo"] == pytest.approx(round(f["w_elo"], 4))       # the committed WTA fit, not DEFAULT_BLEND["atp"]


# ── 5. ranking points: canon's table is the only one ────────────────────────────────────────────────────────

def test_points_come_from_canon_only():
    assert not hasattr(_points, "FALLBACK")
    for tour in ("atp", "wta"):
        for level, draw in (("slam", 128), ("m1000", 96), ("m1000", 56), ("500", 32), ("500", 48), ("250", 32),
                            ("250", 48), ("finals", 8)):
            want = canon.points_table(tour, level, draw)
            got = _points.table(tour, level, draw, 2026)
            keys = {_points._KEYS.get(k, k) for k in want}
            assert set(got) == keys, (tour, level, draw)
            for k, v in want.items():
                assert got[_points._KEYS.get(k, k)] == float(v), (tour, level, draw, k)
    assert _points.table("atp", "ch", 32) == {} and _points.table("atp", "other", 32) == {}


def test_points_match_the_official_charts():
    # WTA 2024 ranking point chart (approved 14 September 2023) and the ATP 2025 rulebook, singles main draw
    wta = {"slam": [2000, 1300, 780, 430, 240, 130, 70, 10], "m1000": [1000, 650, 390, 215, 120, 65, 35, 10],
           "500": [500, 325, 195, 108, 60, 1], "250": [250, 163, 98, 54, 30, 1]}
    atp = {"slam": [2000, 1300, 800, 400, 200, 100, 50, 10], "m1000": [1000, 650, 400, 200, 100, 50, 30, 10],
           "500": [500, 330, 200, 100, 50, 0], "250": [250, 165, 100, 50, 25, 0]}
    rounds = ["W", "F", "SF", "QF", "R16", "R32", "R64", "R128"]
    for tour, tab in (("wta", wta), ("atp", atp)):
        for lv, pts in tab.items():
            t = _points.table(tour, lv, 128 if lv in ("slam", "m1000") else 32)
            assert [t[r] for r in rounds[:len(pts)]] == [float(x) for x in pts], (tour, lv)
    assert _points.table("wta", "250", 32)["QF"] == 54.0
    assert _points.table("wta", "m1000", 56)["R64"] == 10.0 and _points.table("wta", "500", 48)["R32"] == 32.0


# ── 6. the committed fits in the match-page and event-page signatures ───────────────────────────────────────

@pytest.fixture
def fitted_copy(tmp_path, monkeypatch):
    d = tmp_path / "fitted"
    shutil.copytree(_io.FITTED, d)
    monkeypatch.setattr(_io, "FITTED", d)
    return d


def _bump(path: Path, key: str, delta: float):
    j = json.loads(path.read_text(encoding="utf-8"))
    j[key] = j[key] + delta
    path.write_text(json.dumps(j), encoding="utf-8")


@pytest.mark.parametrize("fname,key", [("predict_atp.json", "w_sr"), ("serve_return_atp.json", "version"),
                                       ("elo_params_atp.json", "logloss")])
def test_page_sig_changes_with_every_fit(fitted_copy, fname, key):
    from oddsmarkets.tennis.analytics import matches as MT
    m = {"id": "x", "p1": "a", "p2": "b", "status": "done", "winner": "a", "sets": [[6, 4], [6, 4]], "date": "2026-02-01"}
    s0 = MT.page_sig(m, "atp")
    assert MT.page_sig(m, "atp") == s0 and MT.page_sig(m, "wta") != s0
    _bump(fitted_copy / fname, key, 1)
    assert MT.page_sig(m, "atp") != s0


def test_fits_signature_ignores_line_endings(fitted_copy):
    s0 = _io.fits_signature("wta")
    p = fitted_copy / "predict_wta.json"
    p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert _io.fits_signature("wta") == s0


def test_year_sig_changes_with_the_fits(fitted_copy):
    spec = importlib.util.spec_from_file_location("build_ace_sig", ROOT / "scripts" / "build_ace.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class TD:
        tour = "atp"
    s0 = mod.year_sig(TD(), 2025)
    _bump(fitted_copy / "predict_atp.json", "sigma", 0.01)
    assert mod.year_sig(TD(), 2025) != s0


# ── 7. cold cache: past checkpoints are refitted within the budget, never replaced by the committed fit ─────

def test_cold_cache_budget_skips_past_fits_only(ace_world, monkeypatch):
    from oddsmarkets.tennis import analytics as an
    td = an.TourData("atp", ace_world["today"])
    monkeypatch.setenv("ACE_SR_FIT_BUDGET", "0")
    monkeypatch.setitem(an._SR_BUDGET, "spent", 1.0)
    past = ace_world["today"].replace(day=1) - __import__("datetime").timedelta(days=200)
    assert td.sr_fit(past) is None and past.isoformat() in td.sr_skipped
    cur = td.sr_fit(ace_world["today"] - __import__("datetime").timedelta(days=1))
    assert cur is not None                                          # a current fit is never budgeted
    monkeypatch.delenv("ACE_SR_FIT_BUDGET")
    td2 = an.TourData("atp", ace_world["today"])
    assert td2.sr_fit(past) is not None and not td2.sr_skipped


# ── 8. small ones ───────────────────────────────────────────────────────────────────────────────────────────

def test_validate_hold_window_ends_at_the_last_completed_match():
    syn = pytest.importorskip("oddsmarkets.tennis.models.synthetic")
    ms, _ = syn.make_tour(n_players=20, n_matches=600, seed=3, start=date(2020, 1, 1), days=300, with_stats=True)
    last = max(_io.day(m["date"]) for m in ms)
    ms = ms + [{"id": "sched", "p1": ms[0]["p1"], "p2": ms[0]["p2"], "date": "2099-01-01", "status": "upcoming",
                "surface": "hard", "level": "250", "best_of": 3}]
    v = BT.validate_hold("wta", ms, min_matches=5)
    assert v["through"] == last.isoformat()


def test_next_season_slams_key(ace_world):
    from oddsmarkets.tennis import analytics as an
    from oddsmarkets.tennis.analytics import site as SI
    td = an.TourData("atp", ace_world["today"])
    out = SI.markets_payload(td, {}, {}, {}, {}, None)
    assert f"slams_{td.current + 1}" in out["futures"]
    assert not any(k.startswith("slams_") and k != f"slams_{td.current + 1}" for k in out["futures"])


def test_backtest_driver_has_no_hard_coded_year():
    src = (ROOT / "scripts" / "_tn_backtest_c.py").read_text(encoding="utf-8")
    assert "2027" not in src and "years_on_disk" in src
