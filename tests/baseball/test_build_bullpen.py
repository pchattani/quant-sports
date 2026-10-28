"""scripts/build_bullpen.py end to end on a synthetic season (models disabled so the run takes seconds): every payload
written with its PAYLOADS keys, a failing step isolated into {"ok": false}, index entries kept by partial runs,
the CI guards (past seasons and history kept when their inputs are not on the machine), the hydrate script and the
public-site entry. No network."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _args(roots, *extra):
    return ["--data", str(roots["data"]), "--raw", str(roots["raw"]), "--cache", str(roots["cache"]), "--levels", "mlb",
            "--no-models", "--quick", "--no-market", "--today", "2025-10-01", *extra]


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture
def built(synthetic_world):
    bb = _load("build_bullpen")
    roots = synthetic_world["roots"]
    assert bb.main(_args(roots, "--seasons", "2025")) == 0
    return {"bb": bb, "roots": roots, "world": synthetic_world}


def test_full_build_writes_every_payload(built):
    data = built["roots"]["data"]
    s = data / "mlb" / "2025"
    for name in ("hitters", "pitchers", "fielders", "teams", "season", "schedule", "umpires", "parks", "leaders", "lab", "awards", "manifest"):
        assert (s / f"{name}.json").exists(), name
    hit = _read(s / "hitters.json")
    assert hit["ok"] and {"metrics", "players"} <= set(hit)
    pit = _read(s / "pitchers.json")
    assert "arsenal" in pit
    peers = _read(s / "peers.json")                          # the player page's peer distributions, without the catalogue
    assert peers["ok"] and peers["groups"] and all({"kind", "n", "floor"} <= set(g) for g in peers["groups"].values())
    assert _read(s / "league_types.json")["league_types"] == pit.get("league_types")
    tm = _read(s / "teams.json")
    t = next(iter(tm["teams"].values()))
    assert {"log", "roster", "park", "values", "pct"} <= set(t)
    sea = _read(s / "season.json")
    assert {"standings", "ratings", "postseason", "sim"} <= set(sea)
    sched = _read(s / "schedule.json")
    assert sched["games"] and {"gpk", "date", "model", "market", "line", "probables"} <= set(sched["games"][0])
    lab = _read(s / "lab.json")
    assert set(lab["kinds"]) == {"hitter", "pitcher"} and lab["fields"][0] == "pid"
    # round 8 (the Scouting Room): age, hand and the fielding / framing samples by name, and every catalogue metric
    assert lab["fields"] == ["pid", "name", "team", "pos", "n", "age", "hand", "chances", "called"]
    hcat = _read(s / "hitters.json")
    assert [m["key"] for m in lab["metrics"]["hitter"]] == [m["key"] for m in hcat["metrics"]]
    for kind in ("hitter", "pitcher"):
        for r in lab["rows"][kind]:
            assert len(r) == len(lab["fields"]) + len(lab["metrics"][kind])
            assert r[6] in (None, "L", "R", "S")
    for name in ("umpires", "fielders", "awards"):          # model-backed payloads without models: isolated failures
        p = _read(s / f"{name}.json")
        assert p.get("ok") is False and p.get("reason")
    pages = list((s / "games").glob("*.json"))
    assert len(pages) == len(built["world"]["store"]["games"])
    page = _read(pages[0])
    assert page["pitches"]["rows"] and page["box"]
    idx = _read(data / "index.json")
    for k in ("updated_at", "season", "phase", "today", "recent", "upcoming", "postseason", "leaders", "teams", "levels"):
        assert k in idx, k
    assert idx["levels"]["mlb"]["season"] == 2025
    gl = _read(data / "glossary.json")
    assert gl["groups"]
    pi = _read(data / "players_index.json")
    pid, row = next(iter(pi.items()))
    assert isinstance(row, list) and len(row) == 6
    car = _read(data / "players" / f"{pid}.json")
    for k in ("id", "name", "bats", "throws", "pos", "dob", "debut", "ids", "seasons", "current", "similar", "movement"):
        assert k in car
    assert car["seasons"][0]["season"] == 2025
    assert (data.parent / "assets" / "base.css").exists()


def test_failing_step_writes_ok_false_and_the_build_goes_on(synthetic_world, monkeypatch):
    bb = _load("build_bullpen")
    from oddsmarkets.baseball.analytics import hitters

    def boom(ctx):
        raise RuntimeError("planted")
    monkeypatch.setattr(hitters, "build", boom)
    roots = synthetic_world["roots"]
    assert bb.main(_args(roots, "--seasons", "2025", "--no-careers")) == 0
    s = roots["data"] / "mlb" / "2025"
    h = _read(s / "hitters.json")
    assert h["ok"] is False and "hitters" in h["reason"]
    assert _read(s / "pitchers.json")["ok"] is True
    assert (s / "season.json").exists() and (roots["data"] / "index.json").exists()


def test_partial_runs_keep_the_level_index_entry(built):
    bb, roots = built["bb"], built["roots"]
    before = _read(roots["data"] / "index.json")["levels"]["mlb"]
    # a run that builds no current season (a season not on disk; the current one goes light)
    assert bb.main(_args(roots, "--seasons", "2024", "--no-careers")) == 0
    after = _read(roots["data"] / "index.json")["levels"]["mlb"]
    assert after.get("season") == before.get("season") and after.get("phase") == before.get("phase")
    # a run of another level only
    args = [a if a != "mlb" else "aaa" for a in _args(roots, "--no-careers")]
    assert bb.main(args) == 0
    assert _read(roots["data"] / "index.json")["levels"]["mlb"].get("season") == 2025


def test_past_season_kept_when_its_pitch_table_is_absent(built, tmp_path):
    from oddsmarkets.baseball.models import synthetic_c as S
    bb, roots = built["bb"], built["roots"]
    # a newer current season appears; 2025's pitch table leaves the machine (CI)
    df, store, _ = S.synth_season(n_teams=6, n_games=20, season=2026, seed=3)
    d = roots["data"] / "mlb" / "2026"
    d.mkdir(parents=True)
    (d / "store.json").write_text(json.dumps(store, default=str), encoding="utf-8")
    df.to_parquet(roots["raw"] / "statcast" / "mlb" / "2026.parquet", index=False)
    before = (roots["data"] / "mlb" / "2025" / "hitters.json").read_text(encoding="utf-8")
    (roots["raw"] / "statcast" / "mlb" / "2025.parquet").unlink()
    args = _args(roots, "--no-careers")
    args[args.index("2025-10-01")] = "2026-10-01"
    assert bb.main(args) == 0
    assert (roots["data"] / "mlb" / "2025" / "hitters.json").read_text(encoding="utf-8") == before
    assert _read(roots["data"] / "mlb" / "2026" / "hitters.json")["ok"] is True
    assert _read(roots["data"] / "index.json")["levels"]["mlb"]["season"] == 2026


def test_hydrate_keeps_the_newer_store(bullpen_roots):
    hy = _load("mlb_hydrate")
    p = bullpen_roots["data"] / "mlb" / "2026" / "store.json"
    newer = json.dumps({"updated_at": "2026-10-01T12:00:00Z", "games": {}}).encode()
    assert hy.hydrate("mlb", 2026, fetcher=lambda url: newer)["store"] == "remote"
    assert json.loads(p.read_text())["updated_at"] == "2026-10-01T12:00:00Z"
    older = json.dumps({"updated_at": "2026-09-01T00:00:00Z"}).encode()
    assert hy.hydrate("mlb", 2026, fetcher=lambda url: older)["store"] == "local"
    assert hy.hydrate("mlb", 2026, fetcher=lambda url: None)["store"] == "missing"


def test_public_site_entry():
    spec = importlib.util.spec_from_file_location("setup_public_site", ROOT / "scripts" / "setup_public_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    repo, desc, title, secret, var, wf, keyfile = mod.SITES["bullpen"]
    assert repo == "the-quant-bullpen" and wf == "update_bullpen.yml" and secret == "BULLPEN_DEPLOY_KEY" and var == "BULLPEN_REPO"
    assert title == "oddsmarkets update_bullpen.yml" and keyfile == "oddsmarkets_BULLPEN_DEPLOY_KEY.base64.txt"
    assert desc.startswith("The Quant Bullpen: MLB odds")
    wf_text = (ROOT / ".github" / "workflows" / "update_bullpen.yml").read_text(encoding="utf-8")
    # no schedule since 2 October 2026: the site is built locally (scripts/local_sites.py); kept for manual runs
    assert "cron:" not in wf_text and "workflow_dispatch:" in wf_text
    assert "mlb_hydrate.py" in wf_text and "build_bullpen.py" in wf_text
    assert "git commit" in wf_text and "/tmp/site" in wf_text      # the only commit is to the public site repo


def test_index_digest_this_week(built, tmp_path):
    """index.json "digest": on a build, the stage; from frozen pre-game prices, the week's record, upset and team of the
    week; the chance log carried forward one snapshot a day and the movers against the snapshot a week old; the
    postseason stage lists the series still alive."""
    from datetime import date
    bb = built["bb"]
    idx = _read(built["roots"]["data"] / "index.json")
    assert "stage" in idx["digest"] and idx["digest"]["stage"]["phase"]

    def card(i, day, h, a, hs, as_, p, gtype="R"):
        return {"gpk": str(i), "date": f"2026-09-{day:02d}", "start": f"2026-09-{day:02d}T23:05:00Z", "status": "final", "gtype": gtype,
                "home": h, "away": a, "hs": hs, "as": as_, "model": {"p_home": p}}
    cards = [card(1, 19, "147", "111", 5, 1, 0.62), card(2, 18, "147", "111", 2, 9, 0.66), card(3, 17, "147", "111", 3, 2, 0.58),
             card(4, 16, "119", "137", 1, 2, 0.47), card(5, 2, "119", "137", 6, 0, 0.30)]
    b = bb.Build(tmp_path / "d")
    (tmp_path / "d" / "mlb").mkdir(parents=True)
    b.write("mlb/chance_log.json", {"2026": {"p_postseason": {"2026-09-13": {"147": 0.70, "111": 0.60, "119": 0.50}}}})
    teams = {"147": {"p_postseason": 0.92, "p_ws": 0.15}, "111": {"p_postseason": 0.41, "p_ws": 0.03}, "119": {"p_postseason": 0.55, "p_ws": 0.08}}
    dig = bb.digest_payload(b, cards, teams, None, "regular", 2026, date(2026, 9, 20))
    r = dig["record"]
    assert (r["n"], r["won"], r["upsets"], r["from"], r["to"]) == (4, 3, 1, "2026-09-13", "2026-09-20") and "by" not in r
    assert dig["upset"]["id"] == "2" and dig["upset"]["winner"] == "111" and dig["upset"]["p"] == 0.34   # game 5 is weeks old
    assert dig["hot"]["key"] == "147" and dig["hot"]["w"] == 2
    mv = dig["movers"]
    assert mv["metric"] == "p_postseason" and mv["since"] == "2026-09-13" and mv["up"][0]["key"] == "147" and mv["down"][0]["key"] == "111"
    log = _read(tmp_path / "d" / "mlb" / "chance_log.json")["2026"]
    assert sorted(log["p_postseason"]) == ["2026-09-13", "2026-09-20"] and log["p_ws"]["2026-09-20"]["147"] == 0.15
    st = dig["stage"]
    assert st["played"] == 5 and st["total"] == 5 and st["last"] == "2026-09-19"
    post = {"round": "CS", "series": [{"round": "CS", "round_name": "League Championship Series", "teams": ["147", "111"], "wins": [3, 2], "best_of": 7, "done": False},
                                      {"round": "CS", "round_name": "League Championship Series", "teams": ["119", "137"], "wins": [4, 0], "best_of": 7, "done": True}],
            "teams": {"147": {"p_ws": 0.4}, "111": {"p_ws": 0.1}}}
    st = bb.digest_payload(b, cards, teams, post, "postseason", 2026, date(2026, 10, 20))["stage"]
    assert st["round"] == "CS" and [s["teams"] for s in st["alive"]] == [["147", "111"]]


def test_featured_prefers_the_big_game_over_the_closest(built):
    """digest.featured (the shared significance rule): a League Championship Series Game 7 leads; a dead coin flip
    between two clubs out of the race at 08:00 UTC is left out; a game of a series already decided (an "if
    necessary" Game 7) is never featured."""
    from datetime import datetime, timezone
    bb = built["bb"]
    now = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
    pre = lambda i, start, h, a, p, series=None, gtype="R": {"gpk": i, "start": start, "status": "pre", "gtype": gtype, "home": h, "away": a,
                                                             "model": {"p_home": p}, "series": series}
    cards = [pre("1", "2026-10-21T08:00:00Z", "120", "121", 0.50),
             pre("2", "2026-10-21T00:08:00Z", "147", "111", 0.56, {"desc": "AL Championship Series", "game": 7, "of": 7}, "L"),
             pre("3", "2026-10-21T00:00:00Z", "119", "137", 0.51, {"desc": "NL Championship Series", "game": 7, "of": 7}, "L")]
    teams = {"120": {"p_postseason": 0.0, "p_ws": 0.0}, "121": {"p_postseason": 0.0, "p_ws": 0.0}}
    post = {"series": [{"round": "CS", "teams": ["147", "111"], "wins": [3, 3], "best_of": 7, "done": False},
                       {"round": "CS", "teams": ["119", "137"], "wins": [4, 2], "best_of": 7, "done": True}],
            "teams": {"147": {"p_ws": 0.3}, "111": {"p_ws": 0.2}, "119": {"p_ws": 0.35}, "137": {"p_ws": 0.0}}}
    f = bb.featured_payload(cards, teams, post, now)
    ids = [r["id"] for r in f["today"]]
    assert ids[:1] == ["2"] and "3" not in ids and "1" not in ids
    assert any("Game 7" in w for w in f["today"][0]["why"])
