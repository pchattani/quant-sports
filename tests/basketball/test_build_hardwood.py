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
    for f in ("tokens.css", "quant.css", "quant.js", "quant-charts.js", "plotly-ec.js"):      # the design kit (docs/_design)
        assert (root.parent / "assets" / "qk" / f).exists(), f
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
    assert {"id", "name", "pos", "pool", "dob", "number", "seasons", "current", "similar", "career_awards"} <= set(pc)
    # the player hero's outlined number, from the store's ESPN roster `jersey` (add_players gives each one)
    nums = [_load(f).get("number") for f in careers]
    assert any(n is not None for n in nums) and all(n is None or (n.isdigit() and len(n) <= 2) for n in nums)
    assert len(pc["seasons"]) == 2 and pc["current"]["season"] == 2031
    # role peers (METRICS_SPEC): similar_role per qualified season, the role card for the latest season
    sims = [x for f in careers for x in _load(f).get("similar_role") or []]
    assert sims and {x["season"] for x in sims} <= {2030, 2031}
    assert all(set(x) == {"season", "id", "name", "team", "distance"} for x in sims)
    rc = pc["role_card"]
    assert rc["season"] == 2031 and rc["role"] in ("G", "W", "B") and rc["n"] > 0 and isinstance(rc["pct_role"], dict)
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


def test_jersey_number_rule():
    assert BH.jersey_number("7") == "7" and BH.jersey_number("00") == "00" and BH.jersey_number(23) == "23"
    assert BH.jersey_number(None) is None and BH.jersey_number("") is None and BH.jersey_number("123") is None


def test_index_digest_in_the_build(root):
    """index.json leagues.<L>.digest on a full build: the stage from the schedule, featured from the shared rule, and
    the chance log next to the league's payloads (the front end never reads it)."""
    assert _run(root) == 0
    dig = _load(root / "index.json")["leagues"]["nba"]["digest"]
    assert dig["asof"].startswith(TODAY)
    st = dig["stage"]
    assert st["total"] > 0 and 0 <= st["played"] <= st["total"] and 1 <= st["week"] <= st["weeks"]
    assert set(dig["featured"]) == {"today", "next", "week"}
    if "record" in dig:
        r = dig["record"]
        assert "by" not in r and r["won"] + r["upsets"] + r["draws"] == r["n"]
    log = _load(root / "nba" / "chance_log.json")
    assert list(log) == ["2031"] and list(log["2031"]["p_playoffs"]) == [TODAY]


def _sched(data, games, sim, phase="regular", post=None):
    d = data / "nba" / "2031"
    d.mkdir(parents=True, exist_ok=True)
    (d / "schedule.json").write_text(json.dumps({"ok": True, "games": games}), encoding="utf-8")
    (d / "season.json").write_text(json.dumps({"ok": True, "phase": phase, "sim": {"teams": sim}, "postseason": post,
                                               "format": {"series": [7, 7, 7, 7]}}), encoding="utf-8")


def _g(i, day, h, a, hs, as_, p, status="post", stype="reg", hour=0, mo=3):
    return {"id": str(i), "date": f"2031-{mo:02d}-{day:02d}T{hour:02d}:30:00Z", "status": status, "stype": stype, "home": h, "away": a,
            "hs": hs, "as": as_, "model": {"p_home": p}}


def test_league_digest_week_from_frozen_chances(tmp_path):
    from datetime import date
    b = BH.Build(tmp_path)
    games = [_g(1, 28, "1", "2", 110, 100, 0.70, mo=2), _g(2, 27, "3", "1", 99, 104, 0.80, mo=2), _g(3, 26, "2", "3", 90, 95, 0.40, mo=2),
             _g(4, 25, "1", "3", 120, 101, 0.66, mo=2), _g(5, 2, "2", "1", 140, 80, 0.10, mo=2), _g(6, 27, "2", "3", 100, 90, 0.5, stype="pre", mo=2)]
    sim = {"1": {"p_playoffs": 0.9, "p_title": 0.3}, "2": {"p_playoffs": 0.4, "p_title": 0.02}, "3": {"p_playoffs": 0.6, "p_title": 0.1}}
    _sched(tmp_path, games, sim)
    (tmp_path / "nba" / "chance_log.json").write_text(json.dumps({"2031": {"p_playoffs": {"2031-02-22": {"1": 0.7, "2": 0.6, "3": 0.6}}}}), encoding="utf-8")
    dig = BH.league_digest(b, "nba", 2031, date(2031, 3, 1))
    r = dig["record"]
    assert (r["n"], r["won"], r["upsets"]) == (4, 3, 1)          # the exhibition and the weeks-old game left out
    assert dig["upset"]["id"] == "2" and dig["upset"]["winner"] == "1" and dig["upset"]["p"] == 0.2
    assert dig["hot"]["key"] == "1" and dig["hot"]["w"] == 3
    mv = dig["movers"]
    assert mv["since"] == "2031-02-22" and mv["up"][0]["key"] == "1" and mv["down"][0]["key"] == "2"


def test_featured_prefers_the_big_game_over_the_closest(tmp_path):
    """The shared significance rule: two title contenders at 19:30 New York lead; a dead coin flip between two teams
    with nothing at stake at 08:30 UTC (03:30 New York) and an exhibition do not."""
    from datetime import date
    b = BH.Build(tmp_path)
    games = [_g(10, 2, "5", "6", None, None, 0.50, status="pre", hour=8), _g(11, 2, "1", "3", None, None, 0.63, status="pre", hour=0),
             _g(12, 2, "2", "4", None, None, 0.51, status="pre", stype="pre", hour=0)]
    sim = {"1": {"p_playoffs": 0.95, "p_title": 0.3}, "3": {"p_playoffs": 0.8, "p_title": 0.2}, "5": {"p_playoffs": 0.0, "p_title": 0.0},
           "6": {"p_playoffs": 0.01, "p_title": 0.0}, "2": {"p_playoffs": 0.5, "p_title": 0.05}, "4": {"p_playoffs": 0.5, "p_title": 0.05}}
    _sched(tmp_path, games, sim)
    f = BH.league_digest(b, "nba", 2031, date(2031, 3, 1))["featured"]
    ids = [x["id"] for x in f["today"]]
    assert ids[0] == "11" and ids[-1] == "10"                    # the 03:30 coin flip ranks last, under the exhibition
    assert "two title contenders" in f["today"][0]["why"]


def test_featured_reads_the_finals_series(tmp_path):
    from datetime import date
    b = BH.Build(tmp_path)
    games = [_g(20, 2, "1", "3", None, None, 0.55, status="pre", stype="post", hour=0)]
    post = {"series": [{"teams": ["1", "3"], "wins": {"1": 3, "3": 3}, "round": "NBA Finals"}]}
    _sched(tmp_path, games, {"1": {"p_title": 0.5}, "3": {"p_title": 0.5}}, phase="playoffs", post=post)
    dig = BH.league_digest(b, "nba", 2031, date(2031, 3, 1))
    top = dig["featured"]["today"][0]
    assert top["id"] == "20" and "Game 7: winner takes the series" in top["why"] and "NBA Finals" in top["why"]


def test_progression_fields_and_reference(tmp_path):
    """Round 6: build_hardwood.progression places every season against the qualified players of its role (the
    catalogue's pct_role where it has the key), adds WAR from value.json, the age and the injury absences."""
    cats = {}
    for s in (2029, 2030):
        P = {}
        for i in range(30):
            role = "GWB"[i % 3]
            P[str(i)] = {"name": f"P{i}", "role": role, "qualified": i < 27, "age": 20.0 + i / 10, "gp": 60 + i,
                         "values": {"hpm": i / 10 - 1, "pts100": 20 + i, "ts": 0.5 + i / 300, "games_missed": 22 - i // 2, "injury_dnp": 12 if i == 3 else 0},
                         "pct_role": {"hpm": 50}}
        cats[s] = {"players": P}
        d = tmp_path / "nba" / str(s)
        d.mkdir(parents=True)
        (d / "value.json").write_text(json.dumps({"cols": ["id", "war"], "rows": [[str(i), i / 5] for i in range(30)]}), encoding="utf-8")
    b = BH.Build(tmp_path)
    ref, rows, keys = BH.progression("nba", cats, b)
    assert keys[0] == "hpm" and "war" in keys and "pts100" in keys
    h = rows[(2030, "3")]
    assert h["pg"] == "nba_guards" and h["age"] == 20.3 and h["miss"] == [21, 12]
    assert h["dv"][keys.index("war")] == 0.6 and h["dp"][keys.index("hpm")] == 50     # the catalogue's own percentile
    assert "dp" not in rows[(2030, "28")]                                              # under the floor: values only
    g = ref["seasons"]["2030"]["nba_wings"]
    assert g["n"] == 9 and len(g["m"]["pts100"]) == 5 and ref["seasons"]["2030"]["len"] >= 85


def test_tape_pre_going_in_unit():
    """tape_pre (the no-look-ahead rule for game pages): the computed rows count only regular-season games final before
    the tip (never the game itself or a later one, nor the preseason) with the ratings fitted before the game day; an
    upcoming game gets the snapshot with the season's current ratings; once it starts (live or final, or the tip
    passed) the snapshot is kept unchanged, unless it counts other games than the rows going in."""
    from datetime import date
    from oddsmarkets.basketball.analytics import games as GMS

    def gm(i, day, h, a, hs=None, as_=None, status="post", stype="reg"):
        return {"id": str(i), "date": f"2030-11-{day:02d}T00:30Z", "status": status, "stype": stype, "home": h, "away": a,
                "hs": hs, "as": as_}

    class Ctx:
        teams = ["1", "2", "3"]
        games = {"0": gm(0, 2, "1", "2", 90, 120, stype="pre"), "1": gm(1, 4, "1", "2", 110, 100), "2": gm(2, 6, "3", "1", 99, 101),
                 "3": gm(3, 8, "1", "3", 95, 120), "4": gm(4, 10, "2", "1", status="pre")}
        ratings = {"teams": {"1": {"net": 4.0, "off": 115.0, "def": 111.0}, "2": {"net": -1.0, "off": 110.0, "def": 111.0},
                             "3": {"net": 0.5, "off": 112.0, "def": 111.5}}}
        asked: list = []

        def ratings_before(self, d):
            self.asked.append(d)
            return {"teams": {"1": {"net": 2.0, "off": 113.0, "def": 111.0}, "3": {"net": 1.0, "off": 112.0, "def": 111.0}}}
    ctx = Ctx()
    gi = GMS.GoingIn(ctx)
    # game 3, final: team 1 going in = games 1 and 2 (2-0, +12), not game 3 (lost by 25), not the preseason game 0
    c = gi.rows(ctx.games["3"], "computed")
    assert c["home"] == {"gp": 2, "w": 2, "l": 0, "pct": 1.0, "pd": 12, "net": 2.0, "off": 113.0, "def": 111.0}
    assert c["away"]["gp"] == 1 and c["away"]["w"] == 0 and c["away"]["pd"] == -2 and c["source"] == "computed"
    assert ctx.asked[-1] == date(2030, 11, 7)            # the fit through the day before (US day of a 00:30Z tip)
    assert gi.rows(ctx.games["1"], "computed")["home"]["gp"] == 0
    # game 4, upcoming: the snapshot (team 1 3 games 2-1, the current ratings)
    now = "2030-11-09T12:00:00Z"
    snap = GMS.tape_pre(gi, ctx.games["4"], None, now)
    assert snap["source"] == "snapshot" and snap["away"]["gp"] == 3 and snap["away"]["pd"] == -13 and snap["away"]["net"] == 4.0
    # it starts: the snapshot is kept unchanged (a marker proves it is not recomputed), live or final
    snap["away"]["net"] = 99.9
    for st, hs, as_ in (("in", 40, 38), ("post", 100, 90)):
        g4 = dict(ctx.games["4"], status=st, hs=hs, **{"as": as_})
        assert GMS.tape_pre(gi, g4, snap, "2030-11-10T02:00:00Z") is snap
    # the tip passed with the store still saying "pre": started all the same
    assert GMS.tape_pre(gi, ctx.games["4"], snap, "2030-11-10T02:00:00Z") is snap
    # a snapshot counting other games than the rows going in (a missed build) gives way to the computed rows
    stale = {"before": snap["before"], "source": "snapshot", "home": {"gp": 0}, "away": {"gp": 1, "net": 99.9}}
    got = GMS.tape_pre(gi, dict(ctx.games["4"], status="post"), stale, "2030-11-10T02:00:00Z")
    assert got["source"] == "computed" and got["away"]["gp"] == 3 and got["away"]["net"] == 2.0
    # a postponed game is not started; nothing at all without a table and a snapshot
    assert not GMS.started(dict(ctx.games["4"], status="postponed"), "2030-12-01T00:00:00Z")
    assert GMS.tape_pre(None, dict(ctx.games["4"], status="post"), None, now) is None


def test_tape_pre_in_game_pages(root):
    """End to end: the current season's pages carry tape_pre; a final game's rows exclude the game itself; an upcoming
    game's snapshot survives its start unchanged (the page is rewritten when its status moves)."""
    assert _run(root, "--no-light", "--no-careers") == 0
    d = root / "nba" / "2031"
    st = _load(d / "store.json")
    from oddsmarkets.basketball.analytics.games import _ts
    games = sorted(st["games"].values(), key=lambda g: _ts(g["date"]))
    fin = [g for g in games if g["status"] == "post" and g.get("stype") == "reg"]
    last = fin[-1]
    tp = _load(d / "games" / f"{last['id']}.json")["tape_pre"]
    h = str(last["home"])
    prior = [g for g in fin if _ts(g["date"]) < _ts(last["date"]) and h in (str(g["home"]), str(g["away"]))]
    won = sum(1 for g in prior if (str(g["home"]) == h) == (g["hs"] > g["as"]))
    assert tp["source"] == "computed" and tp["home"]["gp"] == len(prior) and tp["home"]["w"] == won
    assert tp["home"]["pd"] == sum((g["hs"] - g["as"]) * (1 if str(g["home"]) == h else -1) for g in prior)
    assert all(tp[s]["net"] is not None for s in ("home", "away"))
    t_now = _ts(f"{TODAY}T23:59:00Z")
    up = next(g for g in games if g["status"] == "pre" and _ts(g["date"]) > t_now)
    p = d / "games" / f"{up['id']}.json"
    snap = _load(p)["tape_pre"]
    sn = _load(d / "season.json")["ratings"][str(up["home"])]
    assert snap["source"] == "snapshot" and snap["home"]["net"] == sn["net"] and snap["home"]["off"] == sn["off"]
    assert snap["home"]["gp"] == len([g for g in fin if str(up["home"]) in (str(g["home"]), str(g["away"]))])
    # the game is played: its page is rewritten (status moved) and keeps the snapshot as written (marker)
    doc = _load(p)
    doc["tape_pre"]["home"]["net"] = 99.9
    p.write_text(json.dumps(doc), encoding="utf-8")
    st["games"][str(up["id"])].update(status="post", hs=101, **{"as": 99})
    write_store(root, st)
    an._clear()
    day = up["date"][:10]
    assert BH.main(["--leagues", "nba", "--seasons", "2031", "--quick", "--no-market", "--today", day, "--data", str(root),
                    "--no-light", "--no-careers"]) == 0
    after = _load(p)
    kept = after["tape_pre"]
    assert after["status"] == "post" and after["hs"] == 101                       # the page was rewritten
    assert kept["home"]["net"] == 99.9 and kept["source"] == "snapshot" and kept["home"]["gp"] == snap["home"]["gp"]
