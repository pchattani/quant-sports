"""Builder D: scripts/build_gridiron.py end to end on a synthetic season (no network): payload keys against
PAYLOADS.md, an isolated failing step, the index kept when the current season is not built, and the light-season skip."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from oddsmarkets.nfl import analytics as an

ROOT = Path(__file__).resolve().parents[2]
SEASON = 2024
TODAY = "2024-12-20"
CARD_KEYS = {"game_id", "week", "gtype", "kickoff", "home", "away", "hs", "as", "status", "qtr", "clock", "possession", "down", "dist",
             "yl100", "model", "market", "line", "wp_home", "qbs", "weather"}


def _load_build():
    spec = importlib.util.spec_from_file_location("build_gridiron", ROOT / "scripts" / "build_gridiron.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def synth(gridiron_roots):
    from oddsmarkets.nfl.analytics import people
    from oddsmarkets.nfl.models import synthetic_b
    synthetic_b.write_season(gridiron_roots["raw"], season=SEASON, seed=2, n_teams=8, rounds=2)
    synthetic_b.write_season(gridiron_roots["raw"], season=SEASON - 1, seed=3, n_teams=8, rounds=2)
    people.reset()
    an._STORES.clear()
    yield gridiron_roots
    people.reset()


def _args(r, *extra):
    return ["--data", str(r["data"]), "--raw", str(r["raw"]), "--cache", str(r["cache"]), "--today", TODAY, "--no-market", "--quick",
            "--no-models", *extra]


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def test_build_end_to_end(synth):
    bg = _load_build()
    assert bg.main(_args(synth)) == 0
    d = synth["data"]
    idx = _read(d / "index.json")
    assert {"updated_at", "season", "week", "phase", "games", "live", "recent", "standings_top", "playoff_odds", "leaders", "gaps",
            "teams"} <= set(idx)
    assert idx["season"] == SEASON and idx["phase"] in ("preseason", "regular", "playoffs", "offseason")
    for c in idx["games"] + idx["recent"]:
        assert CARD_KEYS <= set(c)
    assert all({"name", "colour", "alt", "division", "conference"} <= set(t) for t in idx["teams"].values())
    s = d / str(SEASON)
    for name in ("players.json", "teams.json", "season.json", "schedule.json", "fourth_downs.json", "leaders.json", "lab.json",
                 "awards.json", "markets.json", "referees.json", "manifest.json"):
        assert (s / name).exists(), name
    cat = _read(s / "players.json")
    assert cat["ok"] and cat["metrics"] and cat["players"]
    sp = _read(s / "season.json")
    assert {"standings", "sim", "draft", "bracket", "ratings"} <= set(sp)
    sched = _read(s / "schedule.json")
    assert sched["games"] and all(CARD_KEYS <= set(c) for c in sched["games"])
    assert list((s / "weeks").glob("*.json"))
    pages = list((s / "games").glob("*.json"))
    assert len(pages) == len(sched["games"])
    page = _read(pages[0])
    assert {"card", "plays", "wp", "drives", "fourth_downs", "box", "key_plays", "awards", "score"} <= set(page)
    assert page["plays"]["cols"][:15] == ["qtr", "clock", "team", "down", "dist", "yl100", "type", "desc", "epa", "wpa", "wp_home_ours",
                                          "wp_home_espn", "ep_before", "ep_after", "players"]
    for name in ("glossary.json", "calibration.json", "history.json", "coaches.json", "players_index.json"):
        assert (d / name).exists(), name
    pi = _read(d / "players_index.json")
    pid, row = next(iter(pi.items()))
    assert len(row) == 5 and (d / "players" / f"{pid}.json").exists()
    assert (d.parent / "assets" / "base.css").exists()
    h = _read(d / "history.json")
    assert set(h["seasons"]) == {SEASON - 1, SEASON}
    # value pages (docs/VALUE_SECTIONS.md): value.json every season; trade.json and needs/<abbr>.json for the current one
    for S_ in (SEASON, SEASON - 1):
        v = _read(d / str(S_) / "value.json")
        assert v["ok"] and v["cols"][:4] == ["pid", "name", "team", "pos"] and v["rows"] and set(v["best"]) == set(v["positions"])
    tr = _read(s / "trade.json")
    assert tr["ok"] and tr["players"] and tr["slots"]["WR"] == 3 and tr["contracts"]["enabled"] is False and tr["cap"] is None
    needs = list((s / "needs").glob("*.json"))
    assert needs and not (d / str(SEASON - 1) / "needs").exists()
    nd = _read(needs[0])
    assert {"units", "positions", "strengths", "weaknesses", "improve", "label"} <= set(nd)
    # the previous season was built light and has game pages (two page seasons)
    assert list((d / str(SEASON - 1) / "games").glob("*.json"))


def test_isolated_failing_step(synth, monkeypatch):
    """A failing catalogue writes {"ok": false} in its place; every other payload and the index are still built."""
    bg = _load_build()
    from oddsmarkets.nfl.analytics import players as PL

    def boom(ctx):
        raise RuntimeError("planted")
    monkeypatch.setattr(PL, "build", boom)
    assert bg.main(_args(synth, "--no-light")) == 0
    s = synth["data"] / str(SEASON)
    cat = _read(s / "players.json")
    assert cat["ok"] is False and "reason" in cat
    assert _read(s / "teams.json")["ok"] and _read(s / "season.json")["ok"] and _read(s / "fourth_downs.json")["ok"]
    assert _read(synth["data"] / "index.json")["season"] == SEASON


def test_index_kept_when_current_not_built(synth):
    bg = _load_build()
    d = synth["data"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.json").write_text(json.dumps({"ok": True, "sentinel": 1}), encoding="utf-8")
    assert bg.main(_args(synth, "--seasons", str(SEASON - 1), "--no-light", "--no-careers")) == 0
    assert _read(d / "index.json") == {"ok": True, "sentinel": 1}
    assert _read(d / str(SEASON - 1) / "players.json")["ok"]


def test_light_season_skipped_when_unchanged(synth):
    bg = _load_build()
    assert bg.main(_args(synth, "--game-page-seasons", "1", "--no-careers")) == 0
    p = synth["data"] / str(SEASON - 1) / "players.json"
    before = p.stat().st_mtime_ns
    assert bg.main(_args(synth, "--game-page-seasons", "1", "--no-careers")) == 0
    assert p.stat().st_mtime_ns == before
    assert bg.main(_args(synth, "--game-page-seasons", "1", "--no-careers", "--force")) == 0
    assert p.stat().st_mtime_ns != before
