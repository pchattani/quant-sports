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
    assert (d.parent / "assets" / "qk" / "quant.js").exists()
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


def test_index_digest_this_week(synth, tmp_path):
    """index.json "digest": on a build, the stage; from frozen pre-game prices, the week's record (a tie has no
    result), upset and team of the week; the chance log carried forward one snapshot a day and the movers against
    the snapshot a week old; the playoff round once the postseason is on."""
    from datetime import date
    mod = _load_build()
    assert mod.main(_args(synth)) == 0
    idx = json.loads((synth["data"] / "index.json").read_text(encoding="utf-8"))
    assert "stage" in idx["digest"] and "featured" in idx["digest"]

    def card(i, day, h, a, hs, as_, p, wk=6, gtype="REG"):
        return {"game_id": f"2026_{wk:02d}_{a}_{h}_{i}", "week": wk, "gtype": gtype, "kickoff": f"2026-10-{day:02d}T17:00:00Z", "status": "final",
                "home": h, "away": a, "hs": hs, "as": as_, "model": {"p_home": p, "source": "frozen"}}
    cards = [card(1, 18, "KC", "LV", 31, 10, 0.78), card(2, 18, "BUF", "MIA", 17, 20, 0.70), card(3, 16, "SF", "LA", 24, 21, 0.58),
             card(4, 15, "DAL", "NYG", 20, 20, 0.60), card(5, 1, "DET", "CHI", 6, 30, 0.85, wk=4)]
    b = mod.Build(tmp_path / "d")
    (tmp_path / "d").mkdir()
    an.write_json(tmp_path / "d" / "chance_log.json", {"2026": {"p_playoffs": {"2026-10-12": {"KC": 0.70, "BUF": 0.90, "MIA": 0.20}}}})
    odds = {"KC": {"p_playoffs": 0.85, "p_sb": 0.15}, "BUF": {"p_playoffs": 0.75, "p_sb": 0.12}, "MIA": {"p_playoffs": 0.30, "p_sb": 0.01}}
    dig = mod.digest_payload(b, cards, odds, "regular", 6, 2026, date(2026, 10, 19))
    r = dig["record"]
    assert (r["n"], r["won"], r["upsets"], r["draws"]) == (3, 2, 1, 0) and "by" not in r    # the DAL tie is left out
    assert dig["upset"]["winner"] == "MIA" and dig["upset"]["p"] == 0.3                       # game 5 is weeks old
    assert dig["hot"]["key"] == "KC" and dig["hot"]["margin"] == 21.0
    mv = dig["movers"]
    assert mv["metric"] == "p_playoffs" and mv["since"] == "2026-10-12" and mv["up"][0]["key"] == "KC" and mv["down"][0]["key"] == "BUF"
    log = json.loads((tmp_path / "d" / "chance_log.json").read_text(encoding="utf-8"))["2026"]
    assert sorted(log["p_playoffs"]) == ["2026-10-12", "2026-10-19"] and log["p_sb"]["2026-10-19"]["KC"] == 0.15
    st = dig["stage"]
    assert (st["week"], st["weeks"], st["played"], st["total"]) == (6, 6, 5, 5) and "round" not in st
    post = cards + [dict(card(9, 20, "KC", "BUF", None, None, 0.55, wk=20, gtype="DIV"), status="scheduled")]
    st = mod.digest_payload(b, post, odds, "playoffs", 20, 2026, date(2026, 10, 19))["stage"]
    assert st["round"] == "DIV" and st["round_name"] == "Divisional round"


def test_featured_prefers_the_big_game_over_the_closest(synth):
    """digest.featured (the shared significance rule): two Super Bowl contenders at 16:25 New York and Bears v Packers
    with both near the playoff line lead; a dead coin flip between two teams out of the race at 05:00 UTC (01:00 New
    York) is left out."""
    from datetime import datetime, timezone
    mod = _load_build()
    now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    pre = lambda i, ko, h, a, p: {"game_id": i, "week": 7, "gtype": "REG", "kickoff": ko, "status": "scheduled", "home": h, "away": a, "model": {"p_home": p}}
    cards = [pre("1", "2026-10-19T05:00:00Z", "TEN", "CLE", 0.50), pre("2", "2026-10-18T20:25:00Z", "KC", "BUF", 0.60), pre("3", "2026-10-18T17:00:00Z", "GB", "CHI", 0.55)]
    odds = {"TEN": {"p_playoffs": 0.02, "p_sb": 0.0}, "CLE": {"p_playoffs": 0.01, "p_sb": 0.0}, "KC": {"p_playoffs": 0.8, "p_sb": 0.2},
            "BUF": {"p_playoffs": 0.75, "p_sb": 0.15}, "GB": {"p_playoffs": 0.5, "p_sb": 0.03}, "CHI": {"p_playoffs": 0.45, "p_sb": 0.02}}
    names = {"GB": {"name": "Green Bay Packers"}, "CHI": {"name": "Chicago Bears"}}
    f = mod.featured_payload(cards, odds, names, now)
    ids = [r["id"] for r in f["today"]]
    assert sorted(ids[:2]) == ["2", "3"] and ("1" not in ids or ids[-1] == "1")
    why = {r["id"]: r["why"] for r in f["today"]}
    assert "two title contenders" in why["2"] and "Bears v Packers" in why["3"]
