"""scripts/build_rink.py end to end on synthetic seasons (no network, no builder B / C models)."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from rink_synth import make_season  # noqa: E402

from oddsmarkets.nhl import analytics as an  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TODAY = "2026-10-20"


def load_build():
    spec = importlib.util.spec_from_file_location("build_rink_t", ROOT / "scripts" / "build_rink.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def site(tmp_path, monkeypatch):
    data, raw, cache = tmp_path / "rink" / "data", tmp_path / "raw", tmp_path / "raw" / "cache"
    monkeypatch.setenv("RINK_DATA", str(data))
    monkeypatch.setenv("RINK_RAW", str(raw))
    monkeypatch.setenv("RINK_CACHE", str(cache))
    an._STORES.clear()
    make_season(data, raw, 20252026, seed=5)
    make_season(data, raw, 20262027, seed=6, today=date(2026, 10, 20), start=date(2026, 10, 8))
    return {"data": data, "raw": raw, "cache": cache,
            "args": ["--data", str(data), "--raw", str(raw), "--cache", str(cache), "--quick", "--no-market", "--no-models", "--no-fetch", "--today", TODAY]}


def rj(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def test_full_build_payload_keys(site):
    B = load_build()
    assert B.main(site["args"]) == 0
    d = site["data"]
    assert (d.parent / "assets" / "base.css").exists()
    for f in ("tokens.css", "quant.css", "quant.js", "quant-charts.js", "plotly-ec.js"):
        assert (d.parent / "assets" / "qk" / f).exists(), f
    idx = rj(d / "index.json")
    for k in ("updated_at", "season", "phase", "today", "live", "recent", "upcoming", "playoff_odds", "leaders", "gaps", "teams"):
        assert k in idx, k
    assert idx["season"] == 20262027
    card = (idx["today"] or idx["upcoming"] or idx["recent"])[0]
    for k in ("game_id", "date", "start", "status", "period", "clock", "home", "away", "hs", "as", "goalies", "model", "market", "line",
              "wp_home", "xg"):
        assert k in card, k
    assert set(idx["teams"]["BOS"]) >= {"name", "colour", "alt", "division", "conference"}
    for s in (20252026, 20262027):
        for f in ("season.json", "schedule.json", "teams.json", "skaters.json", "goalies.json", "lines.json", "leaders.json", "lab.json",
                  "awards.json", "manifest.json"):
            p = rj(d / str(s) / f)
            assert p.get("ok") is not False, (s, f, p)
        assert any((d / str(s) / "games").glob("*.json"))
    assert rj(d / "20262027" / "markets.json")["ok"]
    sk = rj(d / "20252026" / "skaters.json")
    m = sk["metrics"][0]
    assert set(m) >= {"key", "label", "group", "fmt", "lower", "scope", "desc", "stabilises_at"}
    pl = rj(d / "players_index.json")
    pid, row = next(iter(pl.items()))
    assert len(row) == 5 and row[3] <= row[4]
    doc = rj(d / "players" / f"{pid}.json")
    assert {"id", "name", "pos", "seasons", "current", "similar"} <= set(doc)
    for f in ("glossary.json", "calibration.json", "history.json"):
        assert (d / f).exists()
    assert rj(d / "calibration.json")["ok"] is False
    keys = {m["key"]: m for m in sk["metrics"]}
    assert keys["toi_gp"]["fmt"] == "toi_min" and {"rapm_off_se", "rapm_def_se"} <= set(keys)
    # no internal builder references anywhere in the published payloads
    for f in d.rglob("*.json"):
        if f.name != "store.json":
            assert "uilder " not in f.read_text(encoding="utf-8"), f
    hist = rj(d / "history.json")
    assert {r["season"] for r in hist["league"]} >= {20252026} and hist["league"][0]["goals_pg"] > 0
    tm = rj(d / "20252026" / "teams.json")["teams"]["BOS"]["units"]
    assert 0 <= tm["pp_pct"] <= 1 and 0 <= tm["pk_pct"] <= 1
    cur = doc.get("current") or {}
    if cur.get("kind") == "skater" and cur.get("onice"):
        assert set(cur["onice"]["by_strength"]) >= {"5v5"}
    sp = rj(d / "20262027" / "season.json")
    assert "mean_pts" in sp["standings"]["rows"][0]
    lab = rj(d / "20252026" / "lab.json")
    assert set(lab["skaters"]) >= {"cols", "ids", "data"} and len(lab["skaters"]["ids"]) == len(lab["skaters"]["data"]["g"])
    assert len(lab["skaters"]["hand"]) == len(lab["skaters"]["ids"]) and set(lab["skaters"]["hand"]) <= {"L", "R", None}
    # the value section (models off here: no GAR, so value.json carries no rows; trade.json and needs still built)
    v = rj(d / "20252026" / "value.json") if (d / "20252026" / "value.json").exists() else None
    assert v is None or v["ok"]
    tr = rj(d / "20262027" / "trade.json")
    assert tr["ok"] and tr["players"]["rows"] and set(tr["params"]["budget"]) == {"F", "D", "G"}
    needs = list((d / "20262027" / "needs").glob("*.json"))
    assert needs and len(rj(needs[0])["grades"]) == 9
    # the extras (valuation, transactions / deals, fantasy): offline here, so each is written, built or {"ok": false}
    for f in ("valuation.json", "transactions.json", "deals.json", "fantasy.json"):
        p = d / "20262027" / f
        if p.exists():
            doc = rj(p)
            assert doc.get("ok") in (True, False) and (doc.get("ok") or doc.get("reason")), f


def test_isolated_failing_step(site, monkeypatch):
    from oddsmarkets.nhl.analytics import skaters

    def boom(ctx):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(skaters, "build", boom)
    B = load_build()
    assert B.main(site["args"]) == 0
    d = site["data"]
    bad = rj(d / "20262027" / "skaters.json")
    assert bad["ok"] is False and "skaters" in bad["reason"]
    assert rj(d / "20262027" / "goalies.json")["ok"] is True
    assert rj(d / "20262027" / "season.json")["ok"] is True
    assert rj(d / "index.json")["ok"] is True


def test_index_kept_when_current_not_built(site, monkeypatch):
    B = load_build()
    B.main(site["args"])
    d = site["data"]
    before = (d / "index.json").read_text(encoding="utf-8")
    real = B.build_season

    def flaky(b, season, full, cfg, shared):
        if season == 20262027:
            raise RuntimeError("current season failed")
        return real(b, season, full, cfg, shared)
    monkeypatch.setattr(B, "build_season", flaky)
    assert B.main(site["args"]) == 0
    assert (d / "index.json").read_text(encoding="utf-8") == before


def test_light_season_skipped_when_unchanged(site, caplog):
    B = load_build()
    B.main(site["args"] + ["--game-page-seasons", "1"])
    caplog.clear()
    import logging
    caplog.set_level(logging.INFO)
    B.main(site["args"] + ["--game-page-seasons", "1"])
    assert any("20252026: inputs unchanged, skipped" in r.getMessage() for r in caplog.records)
    # the skipped season's catalogues still feed the careers
    assert any(json.loads(p.read_text(encoding="utf-8"))["seasons"][0]["season"] == 20252026
               for p in (site["data"] / "players").glob("*.json"))


def test_page_seasons_and_all_games(site):
    B = load_build()
    B.main(site["args"] + ["--game-page-seasons", "1"])
    d = site["data"]
    assert not (d / "20252026" / "games").exists()
    n_cur = len(list((d / "20262027" / "games").glob("*.json")))
    assert n_cur == len([g for g in rj(d / "20262027" / "schedule.json")["games"]])


def test_players_index_without_careers(site):
    B = load_build()
    assert B.main(site["args"] + ["--no-careers", "--no-light"]) == 0
    d = site["data"]
    idx = rj(d / "players_index.json")
    assert len(idx) == 6 * 20 and all(len(v) == 5 and v[0] for v in idx.values())
    assert not (d / "players").exists()



def test_index_digest_this_week(site, tmp_path):
    """index.json "digest": on a build, the stage; from frozen pre-game chances, the week's record, upset and team of
    the week; the chance log carried forward (a second build the same day replaces that day's snapshot) and the
    movers against the snapshot about a week old."""
    B = load_build()
    assert B.main(site["args"] + ["--no-light", "--no-careers", "--no-history"]) == 0
    st = rj(site["data"] / "index.json")["digest"]["stage"]
    assert st["total"] > 0 and 0 <= st["played"] <= st["total"] and 1 <= st["week"] <= st["weeks"]

    def card(i, day, h, a, hs, as_, p):
        return {"game_id": str(i), "date": f"2026-10-{day:02d}", "start": f"2026-10-{day:02d}T23:00:00Z", "status": "final", "type": "REG",
                "home": h, "away": a, "hs": hs, "as": as_, "model": {"p_home": p}}
    cards = [card(1, 19, "COL", "SJS", 5, 1, 0.72), card(2, 18, "EDM", "CHI", 2, 3, 0.70), card(3, 17, "COL", "EDM", 3, 2, 0.55),
             card(4, 16, "SJS", "CHI", 1, 2, 0.48), card(5, 2, "CHI", "COL", 6, 0, 0.20)]
    b = B.Build(tmp_path / "d")
    (tmp_path / "d").mkdir()
    an.write_json(tmp_path / "d" / "chance_log.json", {"20262027": {"p_playoffs": {"2026-10-13": {"COL": 0.60, "EDM": 0.70, "CHI": 0.30}}}})
    odds = {"COL": {"p_playoffs": 0.80, "p_cup": 0.12}, "EDM": {"p_playoffs": 0.55, "p_cup": 0.06}, "CHI": {"p_playoffs": 0.31, "p_cup": 0.01}}
    dig = B.digest_payload(b, cards, odds, "regular", 20262027, date(2026, 10, 20))
    r = dig["record"]
    assert (r["n"], r["won"], r["expected"], r["draws"], r["upsets"], r["from"], r["to"]) == (4, 3, 2.5, 0, 1, "2026-10-13", "2026-10-20")
    assert dig["upset"]["id"] == "2" and dig["upset"]["winner"] == "CHI" and dig["upset"]["p"] == 0.3   # game 5 is weeks old
    assert dig["hot"]["key"] == "COL" and dig["hot"]["w"] == 2
    mv = dig["movers"]
    assert mv["metric"] == "p_playoffs" and mv["since"] == "2026-10-13" and mv["up"][0]["key"] == "COL" and mv["down"][0]["key"] == "EDM"
    log = rj(tmp_path / "d" / "chance_log.json")["20262027"]
    assert sorted(log["p_playoffs"]) == ["2026-10-13", "2026-10-20"] and log["p_cup"]["2026-10-20"]["COL"] == 0.12
    B.digest_payload(b, cards, odds, "regular", 20262027, date(2026, 10, 20))
    assert sorted(rj(tmp_path / "d" / "chance_log.json")["20262027"]["p_playoffs"]) == ["2026-10-13", "2026-10-20"]


def test_featured_prefers_the_big_game_over_the_closest():
    """digest.featured (the shared significance rule): a game between two clubs whose playoff and Cup chances ride on
    it, at a normal hour, leads; a dead coin flip with nothing at stake at 08:00 UTC (03:00 in New York) does not."""
    from datetime import datetime, timezone
    B = load_build()
    now = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
    cards = [{"game_id": "1", "start": "2026-10-25T08:00:00Z", "status": "scheduled", "type": "REG", "home": "SJS", "away": "CHI", "model": {"p_home": 0.50}},
             {"game_id": "2", "start": "2026-10-24T23:00:00Z", "status": "scheduled", "type": "REG", "home": "COL", "away": "EDM", "model": {"p_home": 0.62}},
             {"game_id": "3", "start": "2026-10-24T23:30:00Z", "status": "scheduled", "type": "PRE", "home": "TOR", "away": "MTL", "model": {"p_home": 0.51}}]
    odds = {"SJS": {"p_playoffs": 0.02, "p_cup": 0.0}, "CHI": {"p_playoffs": 0.01, "p_cup": 0.0}, "COL": {"p_playoffs": 0.6, "p_cup": 0.15},
            "EDM": {"p_playoffs": 0.55, "p_cup": 0.12}, "TOR": {"p_playoffs": 0.5, "p_cup": 0.05}, "MTL": {"p_playoffs": 0.5, "p_cup": 0.05}}
    f = B.featured_payload(cards, odds, {"TOR": {"name": "Toronto Maple Leafs"}, "MTL": {"name": "Montréal Canadiens"}}, now)
    assert [r["id"] for r in f["today"]][:1] == ["2"]
    assert "1" not in [r["id"] for r in f["today"]]
    assert "two title contenders" in f["today"][0]["why"]


def test_tape_pre_going_in_unit():
    """tape_pre (the no-look-ahead rule for game pages): the computed rows count only regular-season games final before
    the start (never the game itself or a later one); an upcoming game gets the snapshot with the published rating;
    once it starts the snapshot is kept unchanged, unless it counts other games than the rows going in."""
    import pandas as pd
    from oddsmarkets.nhl.analytics import games as GM

    class Ctx:
        games = {"1": {"game_id": "1", "start": "2026-10-09T23:00:00Z", "date": "2026-10-09", "status": "final", "home": "BOS", "away": "TOR"},
                 "2": {"game_id": "2", "start": "2026-10-11T23:00:00Z", "date": "2026-10-11", "status": "final", "home": "MTL", "away": "BOS"},
                 "3": {"game_id": "3", "start": "2026-10-13T23:00:00Z", "date": "2026-10-13", "status": "final", "home": "BOS", "away": "MTL"},
                 "4": {"game_id": "4", "start": "2026-10-15T23:00:00Z", "date": "2026-10-15", "status": "scheduled", "home": "TOR", "away": "BOS"}}
    rows = []
    for gid, h, a, gh, ga in (("1", "BOS", "TOR", 4, 1), ("2", "MTL", "BOS", 2, 3), ("3", "BOS", "MTL", 0, 5)):
        for t, gf, gag in ((h, gh, ga), (a, ga, gh)):
            rows.append({"game_id": gid, "team": t, "gt": "REG", "gf_all": gf, "ga_all": gag, "xgf_all": gf * 0.9, "xga_all": gag * 0.9,
                         "xgf_5v5": gf * 0.6, "xga_5v5": gag * 0.6})
    gi = GM.GoingIn(Ctx, pd.DataFrame(rows), {"BOS": 0.42, "TOR": -0.1, "MTL": 0.0},
                    {"ok": True, "weeks": ["2026-10-12"], "teams": {"BOS": [0.3], "TOR": [-0.2], "MTL": [0.1]}})
    # game 3, final: BOS going in = games 1 and 2 only (7 for, 3 against), not game 3 (0-5)
    c = gi.rows(Ctx.games["3"], "computed")
    assert c["home"]["gp"] == 2 and c["home"]["gf_g"] == 3.5 and c["home"]["ga_g"] == 1.5 and c["away"]["gp"] == 1
    assert c["home"]["rating"] == 0.3 and c["rating_asof"] == "2026-10-12" and c["before"] == "2026-10-13T23:00:00Z"
    # game 1, the season opener: nobody had played
    assert gi.rows(Ctx.games["1"], "computed")["home"]["gp"] == 0
    # game 4, upcoming: the snapshot (three BOS games, the published rating)
    now = "2026-10-14T12:00:00Z"
    snap = GM.tape_pre(gi, Ctx.games["4"], None, now)
    assert snap["source"] == "snapshot" and snap["away"]["gp"] == 3 and snap["away"]["rating"] == 0.42
    # it starts: the snapshot is kept unchanged (a marker proves it is not recomputed), live or final
    snap["away"]["rating"] = 9.99
    for st in ("live", "final"):
        g4 = dict(Ctx.games["4"], status=st)
        assert GM.tape_pre(gi, g4, {"tape_pre": snap}, "2026-10-16T01:00:00Z") is snap
    # a start time passed counts as started even before the store says so
    assert GM.tape_pre(gi, Ctx.games["4"], {"tape_pre": snap}, "2026-10-16T01:00:00Z") is snap
    # a snapshot counting other games than the rows going in (a missed build) gives way to the computed rows
    stale = {"before": snap["before"], "source": "snapshot", "home": {"gp": 0}, "away": {"gp": 1, "rating": 9.99}}
    got = GM.tape_pre(gi, dict(Ctx.games["4"], status="final"), {"tape_pre": stale}, "2026-10-16T01:00:00Z")
    assert got["source"] == "computed" and got["away"]["gp"] == 3 and got["away"]["rating"] == 0.3
    # no snapshot and no table: nothing (the page drops the rows)
    assert GM.tape_pre(None, dict(Ctx.games["4"], status="final"), None, now) is None


def test_tape_pre_in_game_pages(site):
    """End to end: every page of the current season carries tape_pre; a final game's rows exclude the game itself
    (games final before its start, from the events); an upcoming game's snapshot survives its start unchanged."""
    B = load_build()
    assert B.main(site["args"] + ["--no-light", "--no-careers", "--no-history"]) == 0
    d = site["data"] / "20262027"
    sched = rj(d / "schedule.json")["games"]
    store = rj(d / "store.json")
    ev = __import__("pandas").read_parquet(site["raw"] / "derived" / "20262027" / "events.parquet")
    fin = sorted((g for g in store["games"].values() if g["status"] == "final"), key=lambda g: g["start"])
    last = fin[-1]
    page = rj(d / "games" / f"{last['game_id']}.json")
    tp = page["tape_pre"]
    assert tp["source"] == "computed" and tp["before"] == last["start"]
    h = last["home"]
    prior = [g for g in fin if g["start"] < last["start"] and h in (g["home"], g["away"])]
    assert tp["home"]["gp"] == len(prior)
    goals = ev[(ev["type"] == "goal") & ev["game_id"].isin([g["game_id"] for g in prior]) & (ev["team"] == h)]
    assert abs(tp["home"]["gf_g"] - len(goals) / len(prior)) < 1e-3
    up = next(g for g in sorted(store["games"].values(), key=lambda g: g["start"]) if g["status"] == "scheduled" and g["start"] > f"{TODAY}T23:59:59Z")
    p = d / "games" / f"{up['game_id']}.json"
    snap = rj(p)["tape_pre"]
    assert snap["source"] == "snapshot" and {"home", "away", "before"} <= set(snap)
    assert snap["home"]["gp"] == len([g for g in fin if up["home"] in (g["home"], g["away"])])
    # the game starts and ends: the page is rewritten (its status moved) and keeps the snapshot as written (marker)
    doc = rj(p)
    doc["tape_pre"]["home"]["rating"] = 9.99
    p.write_text(json.dumps(doc), encoding="utf-8")
    store["games"][str(up["game_id"])].update(status="final", hs=3, **{"as": 2}, period=3, ot=False, so=False)
    (d / "store.json").write_text(json.dumps(store), encoding="utf-8")
    an._STORES.clear()
    day = up["date"]
    args = [a if a != TODAY else day for a in site["args"]]
    assert B.main(args + ["--no-light", "--no-careers", "--no-history"]) == 0
    kept = rj(p)["tape_pre"]
    assert kept["home"]["rating"] == 9.99 and kept["source"] == "snapshot" and kept["home"]["gp"] == snap["home"]["gp"]
    assert len(sched) == len(list((d / "games").glob("*.json")))
