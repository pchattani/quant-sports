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
    tm = _read(s / "teams.json")
    t = next(iter(tm["teams"].values()))
    assert {"log", "roster", "park", "values", "pct"} <= set(t)
    sea = _read(s / "season.json")
    assert {"standings", "ratings", "postseason", "sim"} <= set(sea)
    sched = _read(s / "schedule.json")
    assert sched["games"] and {"gpk", "date", "model", "market", "line", "probables"} <= set(sched["games"][0])
    lab = _read(s / "lab.json")
    assert set(lab["kinds"]) == {"hitter", "pitcher"} and lab["fields"][0] == "pid"
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
    for k in ("id", "name", "bats", "throws", "pos", "dob", "debut", "ids", "seasons", "current", "similar"):
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
