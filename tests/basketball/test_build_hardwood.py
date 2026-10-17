"""scripts/build_hardwood.py end to end on synthetic stores and the recorded fixtures: every payload is written with
the PAYLOADS.md top-level keys, probabilities sum, a failing step is isolated (its payload becomes {"ok": false}),
unchanged light seasons are skipped, and a game page built with play-by-play is never downgraded."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball import store
from oddsmarkets.basketball.models.synthetic import make_store

from .test_analytics_d import add_players, fixture_store, write_store

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_hardwood as BH  # noqa: E402

TODAY = "2031-03-01"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture
def root(tmp_path, monkeypatch):
    data, cache, pbp = tmp_path / "data", tmp_path / "cache", tmp_path / "pbp"
    for k, v in (("HARDWOOD_DATA", data), ("HARDWOOD_CACHE", cache), ("HARDWOOD_PBP", pbp)):
        monkeypatch.setenv(k, str(v))
    an._clear()
    for season, frac, seed in ((2030, 1.0, 1), (2031, 0.5, 2)):
        st, _ = make_store("nba", season, seed=seed, played_frac=frac, n_teams=10, games=24)
        add_players(st, seed)
        write_store(data, st)
    css = tmp_path / "site" / "assets" / "style.css"
    css.parent.mkdir(parents=True)
    css.write_text("body{}", encoding="utf-8")
    monkeypatch.setattr(BH, "CSS_SRC", css)
    yield data
    an._clear()


def _run(data, *extra):
    return BH.main(["--leagues", "nba", "--seasons", "2031", "--quick", "--no-market", "--today", TODAY, "--data", str(data), *extra])


def test_build_writes_every_payload(root):
    assert _run(root) == 0
    d = root / "nba"
    assert (root.parent / "assets" / "base.css").exists()
    idx = _load(root / "index.json")
    lg = idx["leagues"]["nba"]
    assert {"name", "current_season", "seasons", "phase", "today", "next_games", "last_games", "teams", "champions"} <= set(lg)
    assert lg["current_season"] == 2031 and lg["seasons"] == [2031, 2030] and len(lg["teams"]) == 10
    for c in lg["today"] + lg["next_games"] + lg["last_games"]:
        assert {"id", "season", "date", "status", "home", "away", "model", "market"} <= set(c)
    assert {"groups", "model"} <= set(_load(root / "glossary.json"))
    for s in (2030, 2031):
        for name in ("season", "teams", "players", "awards", "schedule", "shots_league", "manifest"):
            assert (d / str(s) / f"{name}.json").exists(), (s, name)
    season = _load(d / "2031" / "season.json")
    assert season["ok"] and season["phase"] == "regular" and season["sim"]["n_sims"] == 400
    assert sum(v["p_title"] for v in season["sim"]["teams"].values()) == pytest.approx(1.0, abs=1e-3)
    assert sum(v["p_playoffs"] for v in season["sim"]["teams"].values()) == pytest.approx(8.0, abs=1e-3)
    old = _load(d / "2030" / "season.json")
    assert old["ok"] and old["sim"] is None and old["standings"]                 # light: no simulation
    sched = _load(d / "2031" / "schedule.json")
    assert len(sched["games"]) == 120 and all(g["season"] == 2031 for g in sched["games"])
    probs = [g["model"]["p_home"] for g in sched["games"] if g["model"]]
    assert probs and all(0 < p < 1 for p in probs)
    pages = list((d / "2031" / "games").glob("*.json"))
    assert len(pages) == 120
    page = _load(pages[0])
    assert {"pregame", "box", "four_factors", "flow", "wp", "shots", "lineups", "rotation", "plays", "awards"} <= set(page)
    assert page["flow"] is None and page["plays"] is None                          # box-only
    for name in ("history", "lab", "calibration", "markets"):
        assert (d / f"{name}.json").exists(), name
    lab = _load(d / "lab.json")
    assert lab["fields"][:4] == ["id", "name", "team", "season"] and lab["years"] == [2030, 2031]
    assert all(len(r) == len(lab["fields"]) for r in lab["rows"])
    hist = _load(d / "history.json")
    assert [r["season"] for r in hist["seasons"]] == [2031, 2030] and hist["first_season"] == 2030
    careers = list((d / "players").glob("*.json"))
    assert len(careers) == 90                                                      # the same 90 ids play both seasons
    pc = _load(careers[0])
    assert {"id", "name", "pos", "pool", "dob", "seasons", "current", "similar", "career_awards"} <= set(pc)
    assert len(pc["seasons"]) == 2 and pc["current"]["season"] == 2031
    cal = _load(d / "calibration.json")
    assert cal["ok"] is False and "reason" in cal                                  # no cached backtest here
    mk = _load(d / "markets.json")
    assert mk["ok"] and mk["futures"] is None and mk["fetched"] is False
    aw = _load(d / "2031" / "awards.json")
    assert aw.get("ok") and aw["keys"] and all(k in aw for k in aw["keys"]) and "6moy" not in aw
    for k in aw["keys"]:
        tot = sum(aw[k]["model"].values())
        # a 24-game synthetic season leaves nobody able to reach the NBA's 65 games (mvp, dpoy, mip): all zero
        assert tot == pytest.approx(1.0, abs=0.02) or (tot == 0 and not any(aw[k]["eligible"].values()))
    assert sum(aw["sixth"]["model"].values()) == pytest.approx(1.0, abs=0.02)
    # the value section: value.json every season, trade.json and needs/<tid>.json for the current one
    for s in (2030, 2031):
        v = _load(d / str(s) / "value.json")
        # the synthetic stores have no stints, so no HPM and no rows; the payload is still well formed
        assert v["ok"] and set(v["best"]) == {"G", "W", "B"} and all(len(r) == len(v["cols"]) for r in v["rows"])
    tr = _load(d / "2031" / "trade.json")
    assert tr["ok"] and tr["players"]["rows"] and len(tr["teams"]) == 10
    assert tr["curves"] and tr["curves"]["shifts"][3] == 0.0 and len(tr["curves"]["teams"]) == 10
    needs = list((d / "2031" / "needs").glob("*.json"))
    assert len(needs) == 10
    nd = _load(needs[0])
    assert len(nd["grades"]) == 7 and len(nd["strengths"]) == 3 and len(nd["weaknesses"]) == 3


def test_failing_step_is_isolated(root, monkeypatch):
    from oddsmarkets.basketball.analytics import players as PL

    def boom(*a, **k):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(PL, "build", boom)
    assert _run(root, "--no-light") == 0
    d = root / "nba" / "2031"
    p = _load(d / "players.json")
    assert p["ok"] is False and "reason" in p
    assert _load(d / "season.json")["ok"] and _load(d / "teams.json")["ok"]        # the rest still built
    assert (root / "index.json").exists()


def test_light_season_skipped_when_unchanged(root):
    assert _run(root) == 0
    p = root / "nba" / "2030" / "players.json"
    m1 = p.stat().st_mtime_ns
    assert _run(root) == 0
    assert p.stat().st_mtime_ns == m1                                              # unchanged inputs: not rebuilt
    assert _run(root, "--force") == 0
    assert p.stat().st_mtime_ns != m1


def test_game_page_never_downgraded(tmp_path, monkeypatch):
    data, cache, pbp = tmp_path / "d", tmp_path / "c", tmp_path / "p"
    for k, v in (("HARDWOOD_DATA", data), ("HARDWOOD_CACHE", cache), ("HARDWOOD_PBP", pbp)):
        monkeypatch.setenv(k, str(v))
    an._clear()
    css = tmp_path / "style.css"
    css.write_text("x", encoding="utf-8")
    monkeypatch.setattr(BH, "CSS_SRC", css)
    from oddsmarkets.basketball.sources import espn
    from .conftest import load_raw
    s, raws = fixture_store()
    for raw in raws.values():
        store.save_pbp("nba", 2026, espn.compact_pbp(raw))
    store.save(s)
    args = ["--leagues", "nba", "--seasons", "2026", "--quick", "--no-market", "--today", "2026-07-01", "--no-light"]
    assert BH.main(args) == 0
    gid = next(iter(raws))
    page = data / "nba" / "2026" / "games" / f"{gid}.json"
    first = _load(page)
    assert first["has_pbp"] and first["flow"] and first["plays"] is not None
    for f in pbp.rglob("*.json.gz"):
        f.unlink()
    an._clear()
    assert BH.main(args + ["--all-games"]) == 0
    again = _load(page)
    assert again["has_pbp"] and again["flow"] == first["flow"]


def test_light_season_built_with_raw_files_is_kept_where_they_are_absent():
    """CI holds no raw play-by-play for past seasons: a light season built locally with the raw files (n_pbp > 0)
    and otherwise unchanged inputs is skipped there, not rebuilt; any other change still rebuilds."""
    local = {"version": 1, "store": "a", "shots": "b", "stints": "c", "n_pbp": 1396}
    assert BH.sig_unchanged(local, dict(local))
    assert BH.sig_unchanged(local, {**local, "n_pbp": 0})                  # CI: no raw files here
    assert not BH.sig_unchanged(local, {**local, "n_pbp": 0, "store": "x"})  # the store changed
    assert not BH.sig_unchanged(local, {**local, "n_pbp": 1400})           # more raw files here: rebuild
    assert not BH.sig_unchanged({**local, "n_pbp": 0}, local)              # raw files arrived: rebuild with them
    assert not BH.sig_unchanged(None, local)
