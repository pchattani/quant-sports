"""A quick Paddock build into a temporary data root from synthetic stores: every PAYLOADS file exists
with its top-level keys, one failing step does not stop the rest (offline: --no-market)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from .conftest import YEAR, payload_keys

ROOT = Path(__file__).resolve().parents[2]


def _build_module():
    spec = importlib.util.spec_from_file_location("build_paddock", ROOT / "scripts" / "build_paddock.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load(p: Path) -> dict:
    assert p.exists(), p
    return json.loads(p.read_text(encoding="utf-8"))


def test_quick_build_writes_every_payload(paddock_data):
    data, cache = paddock_data
    bp = _build_module()
    assert bp.main(["--quick", "--no-market", "--data", str(data), "--cache", str(cache), "--seasons", str(YEAR)]) == 0
    keys = payload_keys()
    for name in ("index.json", "glossary.json", "calibration.json", "markets.json", "elo.json", "lab.json"):
        assert set(_load(data / name)) >= keys[name], name
    assert (data.parent / "assets" / "qk" / "quant.js").exists()   # the shared design kit
    circuits = _load(data / "circuits.json")
    assert set(circuits) == {"circ0", "circ1", "circ2"}
    assert set(next(iter(circuits.values()))) >= {"name", "country", "profile", "history", "records"}

    idx = _load(data / "index.json")
    assert idx["current_season"] == YEAR and idx["seasons"] == [YEAR, YEAR - 1]
    assert idx["next"]["round"] == 4 and idx["last"]["round"] == 3
    assert idx["seasons_meta"][str(YEAR - 1)]["champion"] and idx["seasons_meta"][str(YEAR)]["champion"] is None
    assert all(t["colour"].startswith("#") and len(t["colour"]) == 7 for t in idx["teams"].values())

    for y, full in ((YEAR, True), (YEAR - 1, False)):
        d = data / str(y)
        for name in ("season.json", "drivers.json", "teams.json"):
            assert set(_load(d / name)) >= keys[name], (y, name)
        assert _load(d / "circuits.json")
        n_rounds = 5 if y == YEAR else 4
        for r in range(1, n_rounds + 1):
            race = _load(d / "races" / f"{r}.json")
            assert set(race) >= keys["race"], (y, r)
        season = _load(d / "season.json")
        assert len(season["calendar"]) == n_rounds
        if full:
            ch = season["championship"]
            assert ch and abs(sum(v["p_title"] for v in ch["drivers"].values()) - 1.0) < 1e-3
            assert set(next(iter(ch["drivers"].values()))) >= {"p_title", "exp_points", "p05", "p95", "pos_dist", "magic", "clinched",
                                                               "eliminated"}
            r1 = _load(d / "races" / "1.json")
            assert r1["forecast"]["pre_quali"]["drivers"] and r1["forecast"]["post_quali"]["drivers"]
            assert r1["expected_v_actual"] and r1["awards"]["driver_of_the_day"]["why"]
            nxt = _load(d / "races" / "4.json")
            assert nxt["status"] == "upcoming" and nxt["forecast"]["pre_quali"]["drivers"] and nxt["forecast"]["post_quali"] is None
            dv = _load(d / "drivers.json")["drivers"]["drv0"]["values"]
            assert dv["points_v_expected"] is not None and dv["exp_points"] is not None
            # redesign additions (22 Oct 2026): the per-round title history, the peer group and similar drivers
            th = season["title_history"]
            assert [h["after_round"] for h in th] == [3] and set(th[0]["drivers"]["drv0"]) >= {"p_title", "p05", "p95", "points"}
            cat = _load(d / "drivers.json")
            assert cat["peer_floor"] >= 3 and cat["peer_count"] >= 2
            q = [e for e in cat["drivers"].values() if e["qualified"]]
            assert q and all(e["pct_peer"] for e in q) and all(e["similar"] for e in q)
            assert all(not e["pct_peer"] for e in cat["drivers"].values() if not e["qualified"])
        else:
            assert season["championship"] is None
            assert _load(d / "races" / "1.json")["forecast"]["pre_quali"] is None
        teams = _load(d / "teams.json")["teams"]
        assert set(teams["team0"]) >= {"name", "colour", "values", "pct", "pit", "log"}
        assert set(teams["team0"]["pit"]) >= {"median_ms", "best_ms", "p_under_2500", "stops"}

    # value pages (docs/VALUE_SECTIONS.md): value.json every season with a decomposition; swap.json and needs.json for the
    # current unfinished season only
    for y in (YEAR, YEAR - 1):
        v = _load(data / str(y) / "value.json")
        assert v["ok"] and v["driver_cols"][:3] == ["id", "name", "team"] and v["drivers"] and v["teams"]
    sw = _load(data / str(YEAR) / "swap.json")
    assert sw["ok"] and len(sw["pairs"]) == 40 and set(sw["published"]) == {"n", "drivers", "constructors"}
    nd = _load(data / str(YEAR) / "needs.json")
    assert nd["ok"] and set(nd["teams"]) == {f"team{j}" for j in range(5)}
    assert {"areas", "strengths", "weaknesses", "improve", "best_swaps"} <= set(nd["teams"]["team0"])
    assert not (data / str(YEAR - 1) / "swap.json").exists()
    # fantasy (docs/VALUE_SECTIONS.md section 5): the current season's projections and picks, the site-wide backtest
    ft = _load(data / str(YEAR) / "fantasy.json")
    assert ft["ok"] and ft["projection_ok"] and ft["next"]["round"] == 4 and ft["drivers"] and ft["teams"] and ft["picks"]["top"]
    assert {"driver_cols", "comp", "schedule", "history", "scoring", "excluded", "backtest"} <= set(ft)
    fb = _load(data / "fantasy_backtest.json")
    assert fb["ok"] and fb["metrics"]["drivers_core"]["model"]["n"] > 0
    assert not (data / str(YEAR - 1) / "fantasy.json").exists()

    career = _load(data / "drivers" / "drv0.json")
    assert set(career) >= keys["career"] and len(career["seasons"]) == 2 and career["elo"]
    lab = _load(data / "lab.json")
    assert {r[3] for r in lab["rows"]} == {YEAR, YEAR - 1} and len(lab["fields"]) == len(lab["rows"][0])
    mk = _load(data / "markets.json")
    assert mk["drivers_title"]["available"] is False and mk["drivers_title"]["model"]
    assert _load(data / "calibration.json")["ok"] is False              # no backtest cached in the temp cache


def test_failing_step_is_isolated(paddock_data, monkeypatch):
    data, cache = paddock_data
    bp = _build_module()
    from oddsmarkets.f1.analytics import teams as tms

    def boom(*a, **k):
        raise RuntimeError("planted failure")
    monkeypatch.setattr(tms, "build", boom)
    assert bp.main(["--quick", "--no-market", "--no-careers", "--data", str(data), "--cache", str(cache), "--seasons", str(YEAR)]) == 0
    t = _load(data / str(YEAR) / "teams.json")
    assert t["ok"] is False and "teams" in t["reason"]
    assert _load(data / str(YEAR) / "season.json")["ok"] is True       # everything after the failure was still built
    assert (data / str(YEAR) / "races" / "5.json").exists()


def test_calibration_prefers_the_newer_of_cache_and_committed(tmp_path):
    bp = _build_module()
    committed, cache = tmp_path / "calibration.json", tmp_path / "backtest.json"
    new = {"ok": True, "generated_at": "2026-10-21T23:41:01Z", "races": 269}
    old_cache = {"generated_at": "2026-10-02T21:25:21Z", "races": 267, "seasons_used": {"2014": "complete"}, "metrics": {}}
    committed.write_text(json.dumps(new), encoding="utf-8")
    cache.write_text(json.dumps(old_cache), encoding="utf-8")
    assert bp.pick_calibration(committed, cache)["races"] == 269          # an older CI cache must not win
    newer_cache = dict(old_cache, generated_at="2026-10-30T00:00:00Z", races=271)
    cache.write_text(json.dumps(newer_cache), encoding="utf-8")
    got = bp.pick_calibration(committed, cache)
    assert got["races"] == 271 and got["ok"] and got["updated_at"] == "2026-10-30T00:00:00Z"
    cache.unlink()
    assert bp.pick_calibration(committed, cache)["races"] == 269
    committed.unlink()
    assert bp.pick_calibration(committed, cache)["ok"] is False


def test_livery_alt_colours_ride_with_the_team_colour():
    """`alt` (the second livery colour) for the kit's clash rule (Red Bull v Mercedes): hand-kept, apart from the
    primary, and written only where the table has one (no null)."""
    from oddsmarkets.f1.analytics import season as ssn
    from oddsmarkets.f1.analytics import teams as tms   # noqa: F401  (imports season._alt)

    def hsl_h(h):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        mx, mn = max(r, g, b), min(r, g, b)
        if mx == mn:
            return None
        d = mx - mn
        x = ((g - b) / d) % 6 if mx == r else (b - r) / d + 2 if mx == g else (r - g) / d + 4
        return 60 * x

    for t in ("red_bull", "mercedes", "ferrari", "mclaren", "aston_martin", "alpine", "williams", "haas", "rb", "audi", "cadillac", "sauber"):
        a = ssn.team_alt(t)
        assert a and a.startswith("#") and len(a) == 7, t
        p, q = hsl_h(ssn.KNOWN_COLOURS[t]), hsl_h(a)
        if p is not None and q is not None:
            dh = abs(p - q)
            dh = min(dh, 360 - dh)
            lum = lambda h: sum(w * (lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)(int(h[i:i + 2], 16) / 255) for w, i in ((0.2126, 1), (0.7152, 3), (0.0722, 5)))
            la, lb = lum(ssn.KNOWN_COLOURS[t]), lum(a)
            assert dh >= 50 or (max(la, lb) + 0.05) / (min(la, lb) + 0.05) >= 1.4, t
    assert ssn._alt("red_bull") == {"alt": "#1B2443"} and ssn._alt("nobody") == {}


def _digest_world(tmp_path, race_start, hist=True):
    """A data root with season.json (calendar, standings, progression, championship, title_history) and the last
    race's file (its walk-forward forecast), as the build writes them."""
    d = tmp_path / "d"
    (d / "2026" / "races").mkdir(parents=True)
    season = {"year": 2026, "rounds_done": 2, "rounds_total": 4,
              "calendar": [{"round": 1, "status": "done", "time": "13:00:00Z", "sprint": False}, {"round": 2, "status": "done", "time": "13:00:00Z", "sprint": False},
                           {"round": 3, "status": "next", "sprint": True}, {"round": 4, "status": "upcoming", "sprint": False}],
              "standings": {"drivers": [{"driver": "a", "points": 50.0}, {"driver": "b", "points": 40.0}]},
              "progression": {"rounds": [1, 2, 3, 4], "drivers": {"a": [25, 25, 43, 50], "b": [18, 33, 33, 40], "c": [0, 0, 1, 26]}},
              "championship": {"drivers": {"a": {"p_title": 0.6}, "b": {"p_title": 0.4}}},
              "title_history": [{"after_round": 1, "as_of": "2026-10-04T20:00:00Z", "drivers": {"a": {"p_title": 0.45}, "b": {"p_title": 0.55}}},
                                {"after_round": 2, "as_of": "2026-10-11T20:00:00Z", "drivers": {"a": {"p_title": 0.6}, "b": {"p_title": 0.4}}}] if hist else []}
    (d / "2026" / "season.json").write_text(json.dumps(season), encoding="utf-8")
    race = {"forecast": {"pre_quali": {"drivers": {"a": {"p_win": 0.5}, "b": {"p_win": 0.3}, "c": {"p_win": 0.05}}},
                         "post_quali": {"drivers": {"a": {"p_win": 0.55}, "b": {"p_win": 0.3}, "c": {"p_win": 0.04}}}}}
    (d / "2026" / "races" / "2.json").write_text(json.dumps(race), encoding="utf-8")
    idx = {"current_season": 2026, "last": {"year": 2026, "round": 2, "name": "Two GP", "winner": "c", "date": "2026-10-11", "winner_team": "t"},
           "next": {"year": 2026, "round": 3, "name": "Three GP", "date": race_start[:10], "sessions": {"race": race_start}}}
    return d, idx


def test_index_digest_this_week_in_f1(tmp_path):
    """index.json "digest": the stage, the title-chance movers between the last two rounds, the last race with the
    winner's pre-race chance (after qualifying) and the upset flag, the form driver, and the next race as featured.
    No "record" for F1."""
    from datetime import datetime, timezone
    bp = _build_module()
    d, idx = _digest_world(tmp_path, "2026-10-18T13:00:00Z")
    dig = bp.digest_payload(d, idx, datetime(2026, 10, 17, 20, 0, tzinfo=timezone.utc))
    st = dig["stage"]
    assert (st["done"], st["left"], st["sprints_left"], st["points_left"], st["leader"], st["gap"]) == (2, 2, 1, 58, "a", 10.0)
    assert dig["movers"]["up"][0]["key"] == "a" and dig["movers"]["since_round"] == 1 and dig["movers"]["after_round"] == 2
    last = dig["last"]
    assert last["winner"] == "c" and last["p"] == 0.04 and last["after_quali"] is True and last["fav"] == "a" and last["upset"] is True
    assert last["start"] == "2026-10-11T13:00:00Z"
    assert dig["hot"]["key"] == "c" and dig["hot"]["v"] == 26 and dig["hot"]["rounds"] == [2, 3, 4]
    assert "record" not in dig
    assert [r["id"] for r in dig["featured"]["today"]] == ["3"]


def test_featured_race_only_within_the_week(tmp_path):
    """The Grand Prix leads the page only when it is near: three days out it is the week's event, not today's; ten
    days out it is neither, and the front end leads with the title fight instead. Without two title_history
    snapshots there are no movers."""
    from datetime import datetime, timezone
    bp = _build_module()
    now = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
    d, idx = _digest_world(tmp_path, "2026-10-18T13:00:00Z", hist=False)
    f = bp.digest_payload(d, idx, now)
    assert f["featured"]["today"] == [] and f["featured"]["week"]["id"] == "3" and "movers" not in f
    idx["next"]["sessions"]["race"] = "2026-10-25T13:00:00Z"
    f = bp.digest_payload(d, idx, now)
    assert f["featured"] == {"today": [], "week": None}
