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


# ---------------------------------------------------------------------------------------------- tape_pre (going in)

def _dated(raw: Path, season: int, last_final_week: int) -> None:
    """Give the synthetic schedule game days (week 1 on 8 Sep, a week apart, 13:00 ET) and leave the weeks after
    `last_final_week` unplayed (no score: scheduled)."""
    import pandas as pd
    sp = raw / "raw" / "schedules" / "games.parquet"
    df = pd.read_parquet(sp)
    m = df["season"] == season
    from datetime import date as _d, timedelta as _td
    df.loc[m, "gameday"] = [(_d(season, 9, 8) + _td(days=7 * (int(w) - 1))).isoformat() for w in df.loc[m, "week"]]
    df.loc[m, "gametime"] = "13:00"
    late = m & (df["week"] > last_final_week)
    df["home_score"] = df["home_score"].astype("float")
    df["away_score"] = df["away_score"].astype("float")
    df.loc[late, ["home_score", "away_score"]] = None
    df.to_parquet(sp, index=False)


def test_tape_pre_going_in_unit():
    """tape_pre (the no-look-ahead rule for game pages): the computed rows refit the EPA units on games final before the
    kickoff only (never the game itself or a later one) and take the ratings from the history point that ends before the
    game's date; an upcoming game gets the snapshot with the published ratings; once it starts the snapshot is kept
    unchanged, live or final, unless it counts other games than the rows going in."""
    from datetime import date as _d, timedelta as _td

    from oddsmarkets.nfl.analytics import games as GM
    from oddsmarkets.nfl.analytics import teams as TM
    from oddsmarkets.nfl.models import synthetic_b
    pbp, _, _, sched, _ = synthetic_b.simulate_season(2024, n_teams=8, rounds=2, seed=4)
    games = {}
    for r in sched.to_dict("records"):
        day = _d(2024, 9, 8) + _td(days=7 * (int(r["week"]) - 1))
        fin = int(r["week"]) <= 10
        games[r["game_id"]] = {"game_id": r["game_id"], "week": int(r["week"]), "gtype": "REG", "date": day.isoformat(),
                               "kickoff": f"{day.isoformat()}T13:00:00-04:00", "home": r["home_team"], "away": r["away_team"],
                               "hs": r["home_score"] if fin else None, "as": r["away_score"] if fin else None,
                               "status": "final" if fin else "scheduled"}

    class Ctx:
        pass
    Ctx.games = games
    teams = sorted({g["home"] for g in games.values()})
    hist = {t: [[w, 0.1 * w, 0.05 * w, 0.05 * w] for w in range(1, 15)] for t in teams}
    gi = GM.GoingIn(Ctx, pbp, {t: {"rating": 4.2, "off_rating": 2.0, "def_rating": 2.2} for t in teams}, hist)
    # a week-8 game: its teams going in = their games of weeks 1-7 (same-week games share the kickoff), refitted
    x = next(g for g in games.values() if g["week"] == 8)
    c = gi.rows(x, "computed")
    prior = {gid for gid, g in games.items() if g["week"] < 8}
    assert c["home"]["gp"] == sum(1 for gid in prior if x["home"] in (games[gid]["home"], games[gid]["away"]))
    want = TM.epa_units(pbp[pbp["game_id"].isin(prior)])[x["home"]]
    assert all(abs(c["home"][k] - want[k]) < 5e-4 for k in GM.TAPE_EPA)
    with_it = TM.epa_units(pbp[pbp["game_id"].isin(prior | {x["game_id"]})])[x["home"]]
    assert any(abs(c["home"][k] - with_it[k]) > 1e-3 for k in GM.TAPE_EPA)          # the game itself would move them
    # the rating: week 7's point ends two days after week 7 (before the week-8 game day); week 8's would count the game
    assert c["home"]["rating"] == 0.7 and c["rating_asof"] == (_d(2024, 9, 8) + _td(days=7 * 6 + 2)).isoformat()
    assert set(c["home"]["rank"]) == set(GM.TAPE_EPA) and c["before"] == "2024-10-27T17:00:00Z"
    # an upcoming week-12 game: the snapshot, every final game counted, the published ratings
    y = next(g for g in games.values() if g["week"] == 12)
    now = "2024-11-20T12:00:00Z"
    snap = GM.tape_pre(gi, y, None, now)
    assert snap["source"] == "snapshot" and snap["home"]["rating"] == 4.2
    assert snap["home"]["gp"] == sum(1 for g in games.values() if g["status"] == "final" and y["home"] in (g["home"], g["away"]))
    # it starts: the snapshot is kept unchanged (a marker proves it is not recomputed), live or final, or kickoff passed
    snap["home"]["rating"] = 9.99
    for st in ("live", "final"):
        assert GM.tape_pre(gi, dict(y, status=st), {"tape_pre": snap}, "2024-12-01T00:00:00Z") is snap
    assert GM.tape_pre(gi, y, {"tape_pre": snap}, "2024-12-01T00:00:00Z") is snap
    # a snapshot that counts other games than the rows going in gives way to the computed rows
    stale = dict(snap, home=dict(snap["home"], gp=1))
    got = GM.tape_pre(gi, dict(y, status="final"), {"tape_pre": stale}, "2024-12-01T00:00:00Z")
    assert got["source"] == "computed" and got["home"]["gp"] == snap["home"]["gp"] and got["home"]["rating"] != 9.99
    # the unit matchups of a started game come from the same rows
    mu = GM.matchup_from_tape(snap)
    assert mu["going_in"] and mu["home_off"]["pass"]["off"] == snap["home"]["off_pass_epa"] and mu["home_off"]["pass"]["def"] == snap["away"]["def_pass_epa"]
    assert GM.tape_pre(None, dict(y, status="final"), None, now) is None


def test_tape_pre_in_game_pages(synth):
    """End to end: a final game's page carries the rows going in (its own and later games left out) and its unit matchups
    going in; an upcoming game's snapshot survives its kickoff unchanged."""
    _dated(synth["raw"], SEASON, 11)
    an._STORES.clear()
    bg = _load_build()
    args = _args(synth, "--no-light", "--no-careers")
    args[args.index("--today") + 1] = "2024-11-20"
    assert bg.main(args) == 0
    gdir = synth["data"] / str(SEASON) / "games"
    sched = _read(synth["data"] / str(SEASON) / "schedule.json")["games"]
    fin = [c for c in sched if c["status"] == "final"]
    last = max(fin, key=lambda c: (c["kickoff"], c["game_id"]))
    page = _read(gdir / f"{last['game_id']}.json")
    tp = page["tape_pre"]
    assert tp["source"] == "computed" and tp["before"] == "2024-11-17T17:00:00Z"
    h = last["home"]
    assert tp["home"]["gp"] == sum(1 for c in fin if c["week"] < last["week"] and h in (c["home"], c["away"]))
    assert page["matchups"]["going_in"] and page["matchups"]["home_off"]["pass"]["off"] == tp["home"]["off_pass_epa"]
    up = min((c for c in sched if c["status"] != "final"), key=lambda c: (c["kickoff"], c["game_id"]))
    p = gdir / f"{up['game_id']}.json"
    doc = _read(p)
    snap = doc["tape_pre"]
    assert snap["source"] == "snapshot" and snap["home"]["gp"] == sum(1 for c in fin if up["home"] in (c["home"], c["away"]))
    assert not doc["matchups"].get("going_in")                      # before kickoff: the season's unit matchups
    # it is played: the page is rewritten (status and score moved) and keeps the snapshot as written (marker)
    doc["tape_pre"]["home"]["rating"] = 9.99
    p.write_text(json.dumps(doc), encoding="utf-8")
    import pandas as pd
    sp = synth["raw"] / "raw" / "schedules" / "games.parquet"
    df = pd.read_parquet(sp)
    m = df["game_id"] == up["game_id"]
    df.loc[m, ["home_score", "away_score"]] = [24.0, 17.0]
    df.to_parquet(sp, index=False)
    an._STORES.clear()
    args[args.index("--today") + 1] = "2024-11-25"
    assert bg.main(args) == 0
    kept = _read(p)
    assert kept["card"]["status"] == "final" and kept["tape_pre"]["home"]["rating"] == 9.99 and kept["tape_pre"]["source"] == "snapshot"
    assert kept["matchups"]["going_in"] and kept["matchups"]["rating"]["home"] == 9.99
