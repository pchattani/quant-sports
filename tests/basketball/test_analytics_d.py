"""Builder D: the analytics layer (oddsmarkets/basketball/analytics) on synthetic stores and the recorded
ESPN fixtures: payload shapes per PAYLOADS.md, direction-aware percentiles, lineups and on/off arithmetic,
placeholder and replayed-game handling, the season phase, WPA reattribution, and the .gz loaders."""
from __future__ import annotations

import gzip
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball import canon, pbp, store
from oddsmarkets.basketball.analytics import context as CX
from oddsmarkets.basketball.analytics import games as GMS
from oddsmarkets.basketball.analytics import glossary as GL
from oddsmarkets.basketball.analytics import lineups as LU
from oddsmarkets.basketball.analytics import pbpx
from oddsmarkets.basketball.analytics import players as PL
from oddsmarkets.basketball.analytics import season as SN
from oddsmarkets.basketball.analytics import teams as TM
from oddsmarkets.basketball.models import _io
from oddsmarkets.basketball.models.synthetic import make_store
from oddsmarkets.basketball.sources import espn

from .conftest import GAMES, load_raw

MINUTES = [36, 34, 32, 30, 28, 26, 24, 18, 12]
POS = ["PG", "SG", "SF", "PF", "C", "G", "F", "C", "G"]


# ============================================================================ synthetic roots

def add_players(st: dict, seed: int = 0, prefix: str = "") -> dict:
    """Give a synthetic store (models/synthetic.make_store) player box scores, with scores re-summed from them."""
    rng = np.random.default_rng(seed)
    roster = {}
    for tid in st["teams"]:
        ids = [f"{prefix}{tid}{k:02d}" for k in range(9)]
        roster[tid] = ids
        for k, pid in enumerate(ids):
            st["players"][pid] = {"name": f"Player {tid}-{k}", "short": f"P. {tid}{k}", "pos": POS[k], "pool": canon.pool(POS[k]),
                                  "jersey": str(k), "dob": f"{1990 + k}-03-0{1 + k % 9}", "teams": [tid]}
    for g in st["games"].values():
        if g["status"] != "post":
            continue
        box = {}
        for tid in (g["home"], g["away"]):
            rows = []
            for k, pid in enumerate(roster[tid]):
                m = MINUTES[k]
                fga = int(rng.poisson(m * 0.4)); fgm = int(rng.binomial(fga, 0.47)); tpa = int(rng.binomial(fga, 0.35))
                tpm = min(int(rng.binomial(tpa, 0.36)), fgm); fta = int(rng.poisson(m * 0.12)); ftm = int(rng.binomial(fta, 0.78))
                pts = 2 * (fgm - tpm) + 3 * tpm + ftm
                rows.append([pid, int(k < 5), m * 60, pts, fgm, fga, tpm, tpa, ftm, fta, int(rng.poisson(m * 0.03)),
                             int(rng.poisson(m * 0.12)), int(rng.poisson(m * 0.08)), int(rng.poisson(m * 0.025)),
                             int(rng.poisson(m * 0.02)), int(rng.poisson(m * 0.05)), int(rng.poisson(m * 0.07)), 0])
            box[tid] = {"players": rows, "dnp": [], "team": {}}
        hs, as_ = sum(r[3] for r in box[g["home"]]["players"]), sum(r[3] for r in box[g["away"]]["players"])
        if hs == as_:
            box[g["home"]]["players"][0][3] += 1
            box[g["home"]]["players"][0][8] += 1
            box[g["home"]]["players"][0][9] += 1
            hs += 1
        for tid, mine, theirs in ((g["home"], hs, as_), (g["away"], as_, hs)):
            for r in box[tid]["players"]:
                r[17] = int(round((mine - theirs) * r[2] / 2880))
            t = {k: sum(r[i] for r in box[tid]["players"]) for k, i in (("fgm", 4), ("fga", 5), ("tpm", 6), ("tpa", 7), ("ftm", 8),
                                                                        ("fta", 9), ("oreb", 10), ("dreb", 11), ("ast", 12),
                                                                        ("stl", 13), ("blk", 14), ("tov", 15), ("pf", 16))}
            t.update({"team_tov": 0, "pts_paint": 40, "pts_fastbreak": 12, "pts_off_tov": 14, "largest_lead": 9, "lead_changes": 4})
            box[tid]["team"] = t
        g.update({"box": box, "hs": hs, "as": as_, "periods": 4})
    return st


def write_store(root, st: dict) -> None:
    d = root / st["league"] / str(st["season"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "store.json").write_text(json.dumps(st), encoding="utf-8")


@pytest.fixture
def synth_root(tmp_path, monkeypatch):
    """Two NBA-shaped seasons of 10 teams: 2030 complete, 2031 half played (box scores only)."""
    data, cache, pbp_root = tmp_path / "data", tmp_path / "cache", tmp_path / "pbp"
    monkeypatch.setenv("HARDWOOD_DATA", str(data))
    monkeypatch.setenv("HARDWOOD_CACHE", str(cache))
    monkeypatch.setenv("HARDWOOD_PBP", str(pbp_root))
    an._clear()
    for season, frac, seed in ((2030, 1.0, 1), (2031, 0.5, 2)):
        st, _ = make_store("nba", season, seed=seed, played_frac=frac, n_teams=10, games=24)
        add_players(st, seed)
        write_store(data, st)
    yield data
    an._clear()


def fixture_store():
    """An NBA 2026 store from the recorded summaries (real box scores and play-by-play)."""
    s = store.new_store("nba", 2026)
    raws = {}
    for k in ("reg", "playoff", "ot", "flagrant"):
        raw = load_raw(k)
        g = espn.compact_game(raw)
        store.merge_game(s, g)
        store.mark(s, g["id"])
        for tid, rec in espn.teams_from_summary(raw).items():
            s["teams"][tid] = rec
        for pid, p in espn.players_from_summary(raw).items():
            s["players"][pid] = {k2: v for k2, v in p.items() if k2 != "id"}
        raws[g["id"]] = raw
    return s, raws


@pytest.fixture
def fixture_root(tmp_path, monkeypatch):
    data, cache, pbp_root = tmp_path / "d", tmp_path / "c", tmp_path / "p"
    monkeypatch.setenv("HARDWOOD_DATA", str(data))
    monkeypatch.setenv("HARDWOOD_CACHE", str(cache))
    monkeypatch.setenv("HARDWOOD_PBP", str(pbp_root))
    an._clear()
    s, raws = fixture_store()
    for gid, raw in raws.items():
        store.save_pbp("nba", 2026, espn.compact_pbp(raw))
    store.save(s)
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import bb_derive
    bb_derive.derive_season("nba", 2026)
    yield data, s
    an._clear()


# ============================================================================ helpers and percentiles

def test_past_season_takes_dates_of_birth_from_the_current_store(synth_root):
    """Only the current season's store has dates of birth (the rosters phase); a past season's catalogue
    context fills them in, without touching a date of birth the past store already has."""
    cur = json.loads((synth_root / "nba" / "2031" / "store.json").read_text(encoding="utf-8"))
    old = json.loads((synth_root / "nba" / "2030" / "store.json").read_text(encoding="utf-8"))
    shared = [p for p in old["players"] if p in cur["players"]]
    assert len(shared) >= 2
    a, b = shared[:2]
    for p in cur["players"].values():
        p["dob"] = "2000-01-01"
    for p in old["players"].values():
        p["dob"] = None
    old["players"][b]["dob"] = "1999-05-05"
    write_store(synth_root, cur)
    write_store(synth_root, old)
    an._clear()
    ctx = CX.SeasonContext("nba", 2030, current=2031)
    assert ctx.players[a]["dob"] == "2000-01-01" and ctx.players[b]["dob"] == "1999-05-05"
    assert old["players"][a]["dob"] is None                                   # the store itself is not changed
    assert CX.SeasonContext("nba", 2031, current=2031).players[a]["dob"] == "2000-01-01"

def test_percentiles_direction_aware():
    vals = {"a": 1.0, "b": 2.0, "c": 3.0, "d": None}
    assert an.percentiles(vals) == {"a": 0, "b": 50, "c": 100}
    assert an.percentiles(vals, lower=True) == {"a": 100, "b": 50, "c": 0}
    assert an.ranks(vals) == {"c": 1, "b": 2, "a": 3} and an.ranks(vals, lower=True) == {"a": 1, "b": 2, "c": 3}
    rows = {p: {"values": {"pts": v, "tov": v}} for p, v in (("x", 10.0), ("y", 20.0), ("z", 30.0), ("w", 5.0))}
    metrics = [an.metric("pts", "Points", "S", "1"), an.metric("tov", "Turnovers", "S", "1", lower=True)]
    an.add_percentiles(rows, metrics, ["x", "y", "z"], {"x": "G", "y": "G", "z": "G", "w": "G"})
    assert rows["z"]["pct"]["pts"] > rows["y"]["pct"]["pts"] > rows["x"]["pct"]["pts"]
    assert rows["z"]["pct"]["tov"] < rows["x"]["pct"]["tov"]                     # lower is better
    assert rows["z"]["rank"]["pts"] == 1 and rows["x"]["rank"]["tov"] == 1
    assert "pts" not in rows["w"]["rank"] and rows["w"]["pct"]["pts"] == 0        # unqualified: placed, not ranked
    assert rows["x"]["pct_pool"]["pts"] == rows["x"]["pct"]["pts"]
    assert an.fmt_value(0.123456, "pct") == 0.123 and an.fmt_value(3.7, "int") == 4 and an.fmt_value(None, "1") is None


def test_placeholders_exhibitions_and_replays():
    st, _ = make_store("wnba", 2030, seed=0, played_frac=1.0, n_teams=6, games=10)
    st["teams"]["-1"] = {"name": "TBD", "abbr": "TBD", "conference": None}
    st["teams"]["900"] = {"name": "Japan", "abbr": "JPN", "conference": None}
    gl = list(st["games"].values())
    st["games"]["x1"] = {**gl[0], "id": "x1", "home": "-1", "away": "-1", "status": "pre", "stype": "post"}
    st["games"]["x2"] = {**gl[0], "id": "x2", "home": "900", "away": gl[0]["home"], "stype": "pre"}
    pp = {**gl[1], "id": "pp", "status": "postponed", "date": "2030-05-01T00:00Z", "hs": None, "as": None}
    st["games"]["pp"] = pp
    st["games"]["rp"] = {**gl[1], "id": "rp", "date": "2030-07-01T00:00Z"}
    assert an.placeholder_teams(st) == {"-1", "900"}
    # an All-Star game mislabelled "reg": two sides with one game each among teams with ten
    st["teams"]["901"] = {"name": "Team Stewart", "abbr": "STE", "conference": None}
    st["teams"]["902"] = {"name": "Team Wilson", "abbr": "WIL", "conference": None}
    st["games"]["as"] = {**gl[2], "id": "as", "home": "901", "away": "902", "stype": "reg"}
    assert an.placeholder_teams(st) == {"-1", "900", "901", "902"}
    st["games"].pop("as")
    assert "-1" not in an.member_teams(st) and len(an.member_teams(st)) == 6
    real = an.real_games(st)
    assert "x1" not in real and "x2" not in real and "pp" not in real and "rp" in real
    assert an.superseded(st) == {"pp"}


def test_season_phase():
    t = date(2030, 6, 1)
    g = lambda st, status, d="2030-06-01": {"stype": st, "status": status, "date": d}  # noqa: E731
    assert CX.season_phase({}, t) == "preseason"
    assert CX.season_phase({"1": g("reg", "pre")}, t) == "preseason"
    assert CX.season_phase({"1": g("reg", "post"), "2": g("reg", "pre")}, t) == "regular"
    assert CX.season_phase({"1": g("reg", "post"), "2": g("playin", "pre")}, t) == "playin"
    assert CX.season_phase({"1": g("reg", "post"), "2": g("post", "post"), "3": g("post", "pre")}, t) == "playoffs"
    assert CX.season_phase({"1": g("reg", "post"), "2": g("post", "post")}, t) == "offseason"
    # a stale pending game long past does not keep the playoffs open
    assert CX.season_phase({"1": g("reg", "post"), "2": g("post", "post"), "3": g("post", "pre", "2030-01-01")}, t) == "offseason"


# ============================================================================ lineups

def _stints():
    H = ["h1", "h2", "h3", "h4", "h5"]
    A = ["a1", "a2", "a3", "a4", "a5"]
    rows = [["g1", 0, 600, *H, *A, 20, 20, 30, 20],
            ["g1", 600, 1200, "h6", *H[1:], *A, 20, 20, 18, 22],
            ["g1", 1200, 1440, *H, "a6", *A[1:], 10, 10, 10, 10]]
    return LU.stint_frame({"cols": _io.STINT_COLS, "rows": rows})


def test_lineups_on_off_and_shrinkage():
    ts = LU.team_stints(_stints(), {"g1": {"home": "1", "away": "2"}})
    assert len(ts) == 6 and set(ts["team"]) == {"1", "2"}
    units = LU.lineup_table(ts, "1", 5, {"h1": 2.0, "h2": 0.0}, min_poss=0)
    top = units[0]
    assert top["players"] == sorted(["h1", "h2", "h3", "h4", "h5"]) and top["poss"] == 30.0
    assert top["pts_for"] == 40 and top["pts_against"] == 30
    assert top["net"] == pytest.approx(100 * 40 / 30 - 100 * 30 / 30)
    lo, hi = sorted((top["net"], top["hpm_sum"]))
    assert lo <= top["shrunk_net"] <= hi                                   # between its result and its players' HPM
    pairs = LU.lineup_table(ts, "1", 2, None, min_poss=0)
    assert any(set(u["players"]) == {"h2", "h3"} and u["poss"] == 50.0 for u in pairs)
    oo = LU.on_off(ts)
    h1 = oo["h1"]
    assert h1["poss_on"] == 30.0 and h1["poss_off"] == 20.0
    assert h1["on_net"] == pytest.approx(100 * 40 / 30 - 100)
    assert h1["off_net"] == pytest.approx(100 * 18 / 20 - 100 * 22 / 20)
    assert h1["diff"] == pytest.approx(h1["on_net"] - h1["off_net"])
    rot = LU.rotation(ts, "g1")
    assert rot["1"]["h2"] == [[0.0, 1440.0]] and rot["1"]["h1"] == [[0.0, 600.0], [1200.0, 1440.0]]


def test_shots_on_floor_assigns_the_defending_five():
    st = _stints()
    shots = pd.DataFrame({"game_id": ["g1", "g1", "g1"], "t": [100.0, 700.0, 1300.0], "team": ["1", "2", "2"]})
    on = LU.shots_on_floor(shots, st, {"g1": {"home": "1", "away": "2"}})
    assert on["def_team"].tolist() == ["2", "1", "1"]
    assert set(on.iloc[0][[f"d{i}" for i in range(1, 6)]]) == {"a1", "a2", "a3", "a4", "a5"}
    assert "h6" in set(on.iloc[1][[f"d{i}" for i in range(1, 6)]])


# ============================================================================ catalogues on a synthetic season

PLAYER_KEYS = {"ok", "league", "season", "updated_at", "metrics", "groups", "pools", "min_floor", "players"}
ROW_KEYS = {"name", "team", "pos", "pool", "age", "gp", "min", "qualified", "values", "pct", "pct_pool", "rank"}


def test_player_and_team_catalogues(synth_root):
    ctx = CX.SeasonContext("nba", 2031, current=2031, full=True, sims=300, today=date(2031, 3, 1))
    assert len(ctx.teams) == 10 and ctx.phase == "regular"
    cat = PL.build(ctx)
    assert PAYLOAD_OK(cat, PLAYER_KEYS)
    assert len(cat["metrics"]) >= 120 and len({m["key"] for m in cat["metrics"]}) == len(cat["metrics"])
    assert {m["fmt"] for m in cat["metrics"]} <= {"int", "1", "2", "3", "pct", "prob", "pm", "sec"}
    assert len(cat["players"]) == 90
    r = next(iter(cat["players"].values()))
    assert ROW_KEYS <= set(r)
    q = [p for p, x in cat["players"].items() if x["qualified"]]
    assert q and all(cat["players"][p]["min"] >= cat["min_floor"] for p in q)
    v = cat["players"][q[0]]["values"]
    assert 0 < v["ts"] < 1 and 0 <= v["usg"] < 1 and v["gp"] > 0 and v["age"] is not None
    # starters (more minutes) have higher usage shares of team minutes than the deep bench
    assert cat["players"]["10000"]["values"]["min_share"] > cat["players"]["10008"]["values"]["min_share"]
    # direction-aware: the qualified player with the most turnovers per 100 sits lowest on tov100
    worst = max(q, key=lambda p: cat["players"][p]["values"]["tov100"])
    assert cat["players"][worst]["pct"]["tov100"] == min(cat["players"][p]["pct"]["tov100"] for p in q)
    tcat = TM.build(ctx, cat, {}, None, None)
    assert {"ok", "metrics", "teams"} <= set(tcat) and len(tcat["metrics"]) >= 70
    t = tcat["teams"][ctx.teams[0]]
    assert {"name", "values", "pct", "rank", "log", "roster", "lineups", "rotation", "on_off", "shot_profile", "injuries", "odds"} <= set(t)
    assert t["values"]["w"] + t["values"]["l"] == len(t["log"]) and all(0 < (x["p_win"] or 0) < 1 for x in t["log"])
    assert len(t["rotation"]["players"]) == 9 and len(t["rotation"]["minutes"][0]) == len(t["rotation"]["games"])
    wins = sum(tt["values"]["w"] for tt in tcat["teams"].values())
    losses = sum(tt["values"]["l"] for tt in tcat["teams"].values())
    assert wins == losses


def test_player_catalogue_role_percentiles(synth_root):
    """Rows carry the value.json role (G / W / B) and `pct_role` against qualified players of the same role."""
    from oddsmarkets.basketball.analytics import value as VAL
    ctx = CX.SeasonContext("nba", 2031, current=2031, full=True, sims=300, today=date(2031, 3, 1))
    cat = PL.build(ctx)
    rows = cat["players"]
    roles, _ = VAL.classify_roles(cat)
    assert all(r["role"] == roles[p] for p, r in rows.items())
    assert set(cat["roles"]) == {"G", "W", "B"} and sum(v["n"] for v in cat["roles"].values()) == cat["n_qualified"]
    assert all(set(r["pct_role"]) <= set(PL.ROLE_PCT_KEYS) for r in rows.values())
    for role in ("G", "W", "B"):
        q = [p for p, r in rows.items() if r["qualified"] and r["role"] == role and r["values"].get("pts100") is not None]
        if len(q) < 3:
            continue
        best = max(q, key=lambda p: rows[p]["values"]["pts100"])
        worst_tov = max(q, key=lambda p: rows[p]["values"]["tov_pct"])
        assert rows[best]["pct_role"]["pts100"] == max(rows[p]["pct_role"]["pts100"] for p in q)
        assert rows[worst_tov]["pct_role"]["tov_pct"] == min(rows[p]["pct_role"]["tov_pct"] for p in q)  # lower is better
    json.dumps(cat, allow_nan=False, default=float)


def PAYLOAD_OK(p: dict, keys: set) -> bool:
    missing = keys - set(p)
    assert not missing, missing
    json.dumps(p, allow_nan=False, default=float)
    return True


def test_season_payload_standings_and_sim(synth_root):
    ctx = CX.SeasonContext("nba", 2031, current=2031, full=True, sims=400, today=date(2031, 3, 1))
    cat = PL.build(ctx)
    s = SN.build_season(ctx, cat, None)
    PAYLOAD_OK(s, {"ok", "league", "season", "updated_at", "phase", "format", "standings", "sim", "bracket", "ratings", "rating_paths",
                   "elo", "power", "schedule_difficulty", "leaders"})
    rows = [r for conf in s["standings"].values() for r in conf]
    assert sorted(r["seed"] for r in rows) == list(range(1, 11))              # one seeding group (all East here)
    for conf in s["standings"].values():
        pct = [r["w"] / max(1, r["w"] + r["l"]) for r in conf]
        assert pct == sorted(pct, reverse=True)
        assert conf[0]["gb"] == 0
    st = s["sim"]["teams"]
    assert s["sim"]["n_sims"] == 400 and sum(v["p_title"] for v in st.values()) == pytest.approx(1.0, abs=1e-6)
    assert all(abs(sum(v["seed_dist"]) - 1) < 1e-3 and 0 <= v["p_playoffs"] <= 1 for v in st.values())
    assert set(s["leaders"]) == {"pts", "reb", "ast", "stl", "blk", "3pm", "hpm", "ts"}
    assert len(s["power"]) == 10 and [p[1] for p in s["power"]] == sorted((p[1] for p in s["power"]), reverse=True)
    assert "win_totals" not in s


def test_glossary_covers_every_metric():
    g = GL.build_glossary()
    keys = {(e["kind"], e["key"]) for grp in g["groups"] for e in grp["entries"]}
    assert all(("player", m["key"]) in keys for m in PL.METRICS) and all(("team", m["key"]) in keys for m in TM.METRICS)
    assert all(e["desc"] and e["desc"] != e["label"] for grp in g["groups"] for e in grp["entries"] if e["kind"] == "player")
    assert all(e["desc"] != e["label"] for grp in g["groups"] for e in grp["entries"] if e["kind"] == "team")
    assert len(g["model"]) >= 15 and all({"key", "label", "group", "desc"} <= set(m) for m in g["model"])


# ============================================================================ real games: the game centre and the pbp pass

GAME_KEYS = {"ok", "id", "league", "season", "date", "status", "stype", "home", "away", "hs", "as", "line", "series", "venue",
             "attendance", "pregame", "box", "four_factors", "flow", "wp", "shots", "shot_quality", "lineups", "rotation", "plays", "awards"}


def test_game_centre_from_recorded_play_by_play(fixture_root):
    data, s = fixture_root
    ctx = CX.SeasonContext("nba", 2026, current=2026, full=False, today=date(2026, 7, 1))
    gid = espn.compact_game(load_raw("ot"))["id"]
    pages = {}

    def on_game(g_id, g, parsed):
        pages[g_id] = GMS.build_game(ctx, g_id, parsed)
    res = pbpx.season_pass("nba", 2026, ctx.store, ctx.games, None, on_game=on_game, want_page=lambda g: True)
    assert res["n_parsed"] == 4 and set(pages) == set(ctx.games)
    p = pages[gid]
    assert GAME_KEYS <= set(p) and p["ok"] and p["has_pbp"]
    h, a = p["home"], p["away"]
    assert set(p["box"]) == {h, a} and all(r["min"] is not None for r in p["box"][h]["players"])
    assert sum(r["pts"] for r in p["box"][h]["players"]) == p["hs"]
    ts = [x[0] for x in p["flow"]]
    assert ts == sorted(ts) and p["flow"][-1][1] == p["hs"] - p["as"]
    assert p["shots"]["cols"] == GMS.SHOT_OUT_COLS and len(p["shots"]["rows"]) > 100
    assert set(p["shot_quality"]) == {h, a}
    assert set(p["lineups"]) == {h, a} and all(u["poss"] >= 0 for u in p["lineups"][h])
    assert set(p["rotation"]) == {h, a}
    assert p["pregame"]["model"]["p_home"] is not None and 0 < p["pregame"]["model"]["p_home"] < 1
    assert p["pregame"]["market"]["p_home"] is not None
    assert p["awards"]["player_of_game"]["player"] in {r["id"] for t in (h, a) for r in p["box"][t]["players"]}
    json.dumps(p, allow_nan=False, default=float)


def test_wpa_team_sums_match_the_wp_change(fixture_root):
    """winprob.wpa credits each play to both teams (misses carry the lost possession via the loose-ball
    state), so a team's players sum to its own WP change and the event summary carries defensive WPA."""
    from oddsmarkets.basketball.models import winprob as W
    data, s = fixture_root
    states = []
    raws = {g: store.load_pbp("nba", 2026, g) for g in s["games"]}
    for gid, raw in raws.items():
        states.append(W.states_from_pbp(raw, s["games"][gid], None, "nba"))
    model = W.fit_wp(pd.concat(states, ignore_index=True))
    assert model["ok"]
    for gid, raw in raws.items():
        g = s["games"][gid]
        ge = pbp.parse(raw, g, "nba", 2026)
        r = W.wpa(g, raw, model, ge, "nba")
        h, a = g["home"], g["away"]
        d = r["wp_final"] - r["wp0"]
        assert r["teams"][h] + r["unattributed"][h] == pytest.approx(d, abs=1e-9)
        assert r["teams"][a] + r["unattributed"][a] == pytest.approx(-d, abs=1e-9)
        assert abs(r["unattributed"][h]) < 0.05 and abs(r["unattributed"][a]) < 0.05
        summ = pbpx.event_summary(ge, g, r, "nba")
        assert set(summ["teams"]) == {h, a} and summ["teams"][h]["poss"] > 50
        assert sum(v.get("tov_pbp", 0) for v in summ["players"].values()) > 0
        assert any(v["dwpa"] != 0 for v in summ["wpa"].values())


def test_player_catalogue_with_play_by_play(fixture_root):
    data, s = fixture_root
    ctx = CX.SeasonContext("nba", 2026, current=2026, full=False, today=date(2026, 7, 1))
    res = pbpx.season_pass("nba", 2026, ctx.store, ctx.games, ctx.wp_model)
    ctx.pbp_summaries = res["games"]
    ctx.pbp_totals = pbpx.season_totals(res["games"])
    tables = {t: LU.lineup_table(ctx.team_stints, t, 5, ctx.hpm) for t in ctx.teams}
    cat = PL.build(ctx, None, tables)
    assert cat["has_pbp"]
    withshots = [r for r in cat["players"].values() if r["values"].get("rim_freq") is not None]
    assert len(withshots) > 10
    for r in withshots:
        v = r["values"]
        assert sum(v[f"{z}_freq"] for z in ("rim", "smid", "lmid", "c3", "ab3")) == pytest.approx(1.0, abs=0.01)
    blocks = PL.current_blocks(ctx, cat, tables, {})
    b = next(iter(v for v in blocks.values() if v["shots"]))
    assert b["shots"]["grid"]["cols"][:2] == ["x", "y"] and b["log"] and "zones" in b["shots"]


# ============================================================================ storage: gzipped inputs

def test_gz_loaders_prefer_the_newer_file(tmp_path, monkeypatch):
    import os
    import time
    monkeypatch.setenv("HARDWOOD_DATA", str(tmp_path))
    obj = {"cols": ["a"], "rows": [[1], [2]]}
    store.save_table_gz("nba", 2025, "shots.json", obj)
    assert store.load_table("nba", 2025, "shots.json") == obj                 # only the .gz on disk
    assert _io.read_json(tmp_path / "nba" / "2025" / "shots.json") == obj
    assert _io.exists(tmp_path / "nba" / "2025" / "shots.json")
    newer = {"cols": ["a"], "rows": [[3]]}
    p = store.save_table("nba", 2025, "shots.json", newer)
    t = time.time() + 5
    os.utime(p, (t, t))                                                         # plain is newer: it wins
    assert store.load_table("nba", 2025, "shots.json") == newer
    assert _io.read_json(tmp_path / "nba" / "2025" / "shots.json") == newer
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import bb_pack
    out = bb_pack.pack_season("nba", 2025, remove_plain=True)
    assert out and not p.exists()
    with gzip.open(out[0], "rt", encoding="utf-8") as fh:
        assert json.load(fh) == newer
    assert store.load_table("nba", 2025, "shots.json") == newer


def test_espn_predictor_parsed_and_kept():
    raw = load_raw("reg")
    g = espn.compact_game(raw)
    assert g["predictor"] is None                                               # this summary has none
    raw2 = dict(raw)
    raw2["predictor"] = {"homeTeam": {"id": g["home"], "gameProjection": "61.5"}, "awayTeam": {"id": g["away"], "gameProjection": "38.5"}}
    g2 = espn.compact_game(raw2)
    assert g2["predictor"] == {"home": 0.615}
    s = store.new_store("nba", 2026)
    store.merge_game(s, g2)
    store.merge_game(s, g)                                                      # a later refetch without it keeps it
    assert s["games"][g["id"]]["predictor"] == {"home": 0.615}


def test_role_similar_and_role_card(synth_root):
    """similar_role: k nearest qualified players of the same role and season on the spec's weighted features; the
    player file's role_card is the small copy of pct_role and the peer facts."""
    from oddsmarkets.basketball.analytics import value as VAL
    from oddsmarkets.common import similar as SIM
    ctx = CX.SeasonContext("nba", 2031, current=2031, full=True, sims=300, today=date(2031, 3, 1))
    cat = PL.build(ctx)
    rows = cat["players"]
    q = [p for p, r in rows.items() if r["qualified"]]
    with_sim = [p for p in q if rows[p].get("similar_role")]
    assert with_sim and all("similar_role" not in r for p, r in rows.items() if not r["qualified"])
    for p in with_sim:
        nb = rows[p]["similar_role"]
        assert 1 <= len(nb) <= 5 and all(x["id"] != p and rows[x["id"]]["qualified"] for x in nb)
        assert all(rows[x["id"]]["role"] == rows[p]["role"] for x in nb)
        assert [x["distance"] for x in nb] == sorted(x["distance"] for x in nb)
        assert set(nb[0]) == {"id", "name", "team", "distance"}
    # the same answer from the shared recipe directly
    p = with_sim[0]
    role = rows[p]["role"]
    mem = [x for x in q if rows[x]["role"] == role]
    cfg = SIM.group_config("basketball", "nba_" + PL.ROLE_GROUP[role])
    Z = SIM.zscore(SIM.matrix([rows[x] for x in mem], cfg["features"]))
    w = np.array([cfg["weights"][f] for f in cfg["features"]])
    assert [mem[j] for j, _ in SIM.nearest(Z, mem.index(p), w, 5)] == [x["id"] for x in rows[p]["similar_role"]]
    # seasons built before the role fields: the role comes from the value.json rule
    bare = {k: {kk: vv for kk, vv in r.items() if kk not in ("role", "pct_role", "similar_role")} for k, r in rows.items()}
    ref = VAL.classify_roles({"players": bare})[0]
    assert PL._roles_of(bare) == {k: ref.get(k, "W") for k in bare}
    card = PL.role_card(rows, p, "nba", 2031, cat)
    assert card["role"] == role and card["group"] == "nba_" + PL.ROLE_GROUP[role]
    assert card["n"] == cat["roles"][role]["n"] and card["min_floor"] == cat["min_floor"] and card["qualified"]
    assert card["pct_role"] == rows[p]["pct_role"]
    json.dumps(card, allow_nan=False)
