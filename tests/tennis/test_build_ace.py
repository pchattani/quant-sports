"""Builder D: scripts/build_ace.py end to end on the synthetic world (no network: --no-market), payload keys per
PAYLOADS.md, failing-step isolation, the index guard and the manifests."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def build_mod():
    spec = importlib.util.spec_from_file_location("build_ace_mod", ROOT / "scripts" / "build_ace.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _args(world, *extra):
    return ["--tours", "atp", "--no-market", "--quick", "--match-page-years", "1", "--today", world["today"].isoformat(),
            "--data", str(world["data"]), "--cache", str(world["cache"]), *extra]


def _j(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def test_build_writes_every_payload(ace_world_small, build_mod):
    assert build_mod.main(_args(ace_world_small)) == 0
    d = ace_world_small["data"]
    assert (d.parent / "assets" / "base.css").exists()
    idx = _j(d / "index.json")
    t = idx["tours"]["atp"]
    assert set(t) >= {"name", "year", "years", "live", "today", "recent", "upcoming", "events_now", "elo_top", "race_top"}
    assert t["year"] == 2026 and t["years"] == [2025, 2026]
    assert set(t["elo_top"]) == {"all", "hard", "clay", "grass"} and len(t["elo_top"]["all"]) == 10
    assert t["events_now"] and t["events_now"][0]["event"] == ace_world_small["live_event"]
    assert t["events_now"][0]["favourite"][1] > 0
    for k in ("glossary.json",):
        assert _j(d / k)["groups"]
    a = d / "atp"
    rk = _j(a / "rankings.json")
    assert set(rk) >= {"date", "official", "elo", "race", "to_defend"}
    assert rk["official"][0][:3] == [1, ace_world_small["order"][0], 4900] and len(rk["official"][0]) == 4
    race = _j(a / "race.json")
    assert race.get("ok") is False or set(race) >= {"n_sims", "finals_qual", "year_end_no1", "rank_dist", "points",
                                                    "remaining_events", "market"}
    elo = _j(a / "elo.json")
    assert set(elo) >= {"current", "peaks", "history"}
    cat = _j(a / "players.json")
    assert cat["year"] == 2026 and cat["metrics"] and cat["players"]
    assert _j(a / "2025" / "players.json")["year"] == 2025
    ev = _j(a / "2026" / "events.json")["events"]
    assert ev[ace_world_small["live_event"]]["page"] is True
    assert set(ev[ace_world_small["live_event"]]) >= {"name", "level", "surface", "indoor", "start", "end", "status", "champion", "runner_up",
                                                 "draw_size"}
    sch = _j(a / "2026" / "schedule.json")["matches"]
    assert sch and set(sch[0]) >= {"id", "event", "round", "date", "status", "p1", "p2", "winner", "sets", "model"}
    page = _j(a / "events" / f"{ace_world_small['live_event']}.json")
    assert page["sim"] and page["sim"]["n_sims"] == 1000
    assert _j(a / "events" / f"{ace_world_small['done_event']}.json")["event"]["champion"]
    mids = [m["id"] for m in sch]
    mp = _j(a / "matches" / f"{mids[0].replace(':', '_')}.json")
    assert set(mp) >= {"id", "pre", "wp", "stats", "inferred", "awards"}
    hist = _j(a / "history.json")["events"]
    assert hist["syn-open"]["champions"][0][0] == 2025
    pi = _j(a / "players_index.json")["players"]
    p0 = ace_world_small["order"][0]
    assert pi[p0][0] == f"Player {p0[-3:]}" and pi[p0][3] == 1
    lab = _j(a / "lab.json")
    assert lab["fields"][:7] == ["id", "name", "year", "qualified", "rank", "age", "hand"] and lab["rows"] and len(lab["rows"][0]) == len(lab["fields"])
    assert set(lab["years"]) == {2025, 2026}
    mk = _j(a / "markets.json")
    assert set(mk) >= {"updated_at", "matches", "futures"}
    assert _j(a / "calibration.json")["ok"] is False
    assert _j(a / "model.json")["elo"]["w_surf"] is not None
    assert lab["surface"]["rows"]
    val = _j(a / "value.json")                                  # the Value section (analytics/value.py)
    assert val["ok"] and set(val) >= {"breakout", "luck", "value", "market"} and val["breakout"]["rows"]
    assert _j(a / "value_validation.json")["ok"]
    assert any(g["name"].startswith("Value:") for g in _j(d / "glossary.json")["groups"])
    car = _j(a / "players" / f"{p0.replace(':', '_')}.json")
    assert car["id"] == p0 and car["seasons"] and car["elo"] and car["results"]
    assert car["current"]["rank"] == 1
    assert len(car["results_all"]) >= len(car["results"]) and len(car["results_all"][0]) == 7
    man = _j(a / "manifest.json")
    assert man["pages"] and man["files"] and set(man["years"]) == {"2025", "2026"}
    # x:<slug> ids become x_<slug> file names: nothing with a colon on disk
    assert not any(":" in p.name for p in a.rglob("*"))


def test_second_run_skips_unchanged(ace_world_small, build_mod, caplog):
    assert build_mod.main(_args(ace_world_small)) == 0
    d = ace_world_small["data"] / "atp"
    car = sorted((d / "players").glob("*.json"))[0]
    done_page = d / "events" / f"{ace_world_small['done_event']}.json"
    t_car, t_ev = car.stat().st_mtime_ns, done_page.stat().st_mtime_ns
    caplog.set_level("INFO")
    assert build_mod.main(_args(ace_world_small)) == 0
    assert car.stat().st_mtime_ns == t_car                      # unchanged career not rewritten
    assert done_page.stat().st_mtime_ns == t_ev                 # unchanged event page (a light year) not rewritten
    assert "2025 light: inputs unchanged, skipped" in caplog.text
    assert "match pages due" in caplog.text


def test_failing_step_is_isolated(ace_world_small, build_mod, monkeypatch):
    from oddsmarkets.tennis.analytics import players as PL
    from oddsmarkets.tennis.analytics import race as RC

    def boom(*a, **k):
        raise RuntimeError("planted failure")
    monkeypatch.setattr(PL, "build", boom)
    monkeypatch.setattr(RC, "simulate", boom)
    assert build_mod.main(_args(ace_world_small, "--no-careers")) == 0
    a = ace_world_small["data"] / "atp"
    cat = _j(a / "2026" / "players.json")
    assert cat["ok"] is False and "catalogue" in cat["reason"]
    race = _j(a / "race.json")
    assert race["ok"] is False
    # the rest of the build went on
    assert _j(a / "rankings.json")["official"]
    assert _j(a / "events" / f"{ace_world_small['live_event']}.json")["draw"]
    assert _j(ace_world_small["data"] / "index.json")["tours"]["atp"]["elo_top"]


def test_partial_run_keeps_index_entry(ace_world_small, build_mod):
    assert build_mod.main(_args(ace_world_small, "--no-careers")) == 0
    idx = ace_world_small["data"] / "index.json"
    before = _j(idx)["tours"]["atp"]
    # a run that does not build the current year must not touch the tour's entry
    assert build_mod.main(_args(ace_world_small, "--no-careers", "--years", "2025", "--no-light")) == 0
    assert _j(idx)["tours"]["atp"] == before
    # nor one whose index step fails
    from oddsmarkets.tennis.analytics import site as SI
    orig = SI.index_entry
    try:
        SI.index_entry = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("planted"))
        assert build_mod.main(_args(ace_world_small, "--no-careers", "--no-light")) == 0
    finally:
        SI.index_entry = orig
    assert _j(idx)["tours"]["atp"] == before


def test_index_digest_this_week(ace_world_small, build_mod):
    """tours[T].digest ("This week in tennis") on a full build: the stage with the live event, the featured block,
    and data/<T>/chance_log.json written when the season simulation ran."""
    assert build_mod.main(_args(ace_world_small)) == 0
    d = ace_world_small["data"]
    dig = _j(d / "index.json")["tours"]["atp"]["digest"]
    assert dig["asof"].startswith(ace_world_small["today"].isoformat())
    assert set(dig["featured"]) == {"today", "week"}
    assert dig["stage"]["now"] and dig["stage"]["now"][0]["id"] == ace_world_small["live_event"]
    for r in dig["featured"]["today"]:
        assert r["score"] >= 40 and isinstance(r["why"], list)
    if "record" in dig:
        assert dig["record"]["won"] + dig["record"]["upsets"] + dig["record"]["draws"] == dig["record"]["n"]
    race = _j(d / "atp" / "race.json")
    if race.get("ok") is not False and race.get("finals_qual"):
        assert "2026" in _j(d / "atp" / "chance_log.json")
