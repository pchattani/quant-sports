"""Data layer: ESPN parsing, stores, possessions, lineups, shots (recorded fixtures, no network)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from oddsmarkets.basketball import canon, pbp, store
from oddsmarkets.basketball.sources import espn

from .conftest import GAMES, PBP_GAMES, A, H, load_json, load_raw

ROOT = Path(__file__).resolve().parents[2]
SUM = {"pts": 3, "fgm": 4, "fga": 5, "tpm": 6, "tpa": 7, "ftm": 8, "fta": 9, "oreb": 10, "dreb": 11, "ast": 12, "stl": 13, "blk": 14, "pf": 16}


@pytest.fixture(scope="module")
def parsed():
    out = {}
    for name in GAMES:
        raw = load_raw(name)
        g = espn.compact_game(raw)
        p = espn.compact_pbp(raw)
        _, league, season = GAMES[name]
        ev = pbp.parse(p, g, league, season) if p else None
        out[name] = (raw, g, p, ev, league, season)
    return out


# ── compact_game ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", list(GAMES))
def test_compact_game_box_sums(parsed, name):
    raw, g, *_ = parsed[name]
    assert g["status"] == "post" and g["home"] != g["away"]
    assert set(g["box"]) == {g["home"], g["away"]}
    for side, tid, score in (("home", g["home"], g["hs"]), ("away", g["away"], g["as"])):
        assert sum(g["line"][side]) == score
        rows = g["box"][tid]["players"]
        assert all(len(r) == len(store.BOX_COLS) for r in rows)
        assert sum(r[3] for r in rows) == score
        team = g["box"][tid]["team"]
        for k, i in SUM.items():
            if k != "pts":
                assert team[k] == sum(r[i] or 0 for r in rows), (name, k)
        assert sum(r[1] for r in rows) == 5                         # five starters
        assert team["tov"] >= sum(r[15] for r in rows) and team["team_tov"] == team["tov"] - sum(r[15] for r in rows)
        assert team["fgm"] * 2 + team["tpm"] + team["ftm"] == score
    secs = sum(r[2] for tid in g["box"] for r in g["box"][tid]["players"])
    reg = canon.regulation_s(GAMES[name][1], GAMES[name][2]) + (g["periods"] - 4) * canon.OT_S
    assert abs(secs - 10 * reg) <= 10 * 60                            # whole-minute rounding


@pytest.mark.parametrize("name", ["reg", "playoff", "ot", "flagrant", "wnba"])
def test_espn_team_line_agrees_with_player_sums(parsed, name):
    """On modern games ESPN's own team line equals the player sums (in 2017-18 it is shifted; we use the sums)."""
    raw, g, *_ = parsed[name]
    for t in raw["boxscore"]["teams"]:
        tid = str(t["team"]["id"])
        vals = {s["name"]: s["displayValue"] for s in t["statistics"]}
        fgm, fga = (int(x) for x in vals["fieldGoalsMade-fieldGoalsAttempted"].split("-"))
        mine = g["box"][tid]["team"]
        assert (fgm, fga) == (mine["fgm"], mine["fga"])
        assert int(vals["assists"]) == mine["ast"] and int(vals["steals"]) == mine["stl"] and int(vals["blocks"]) == mine["blk"]
        assert int(vals["totalTurnovers"]) == mine["tov"]


def test_compact_game_details(parsed):
    g = parsed["playoff"][1]
    assert g["stype"] == "post" and g["series"] == {"round": "NBA Finals", "game": 5, "summary": "NY wins series 4-1"}
    assert g["odds"]["provider"] == "DraftKings" and g["odds"]["spread_home"] == -5.5 and g["odds"]["ml_home"] < 0 < g["odds"]["ml_away"]
    assert g["injuries"] == {}                                       # summary injuries are today's, not the game's
    assert parsed["reg"][1]["neutral"] is True and parsed["reg"][1]["venue"]["city"] == "Berlin"
    assert parsed["ot"][1]["periods"] == 5 and len(parsed["ot"][1]["line"]["home"]) == 5
    old = parsed["boxonly"][1]
    assert old["has_pbp"] is False and old["series"] is None and old["odds"] is None
    assert all(r[17] is None for t in old["box"].values() for r in t["players"])   # no plus-minus before ~2007
    assert parsed["boxonly"][2] is None
    assert all(parsed[k][1]["has_pbp"] for k in PBP_GAMES)
    dnp = parsed["playoff"][1]["box"]["18"]["dnp"]
    assert dnp and all(len(x) == 2 for x in dnp)


def test_scoreboard_event_and_calendar():
    sb = load_json("scoreboard_nba_20260115.json.gz")
    games = [espn.compact_event(e) for e in sb["events"]]
    assert len(games) == 9 and all(g["status"] == "post" and g["hs"] and g["as"] and g["box"] == {} for g in games)
    assert all(sum(g["line"]["home"]) == g["hs"] for g in games)
    berlin = next(g for g in games if g["id"] == "401810433")
    assert berlin["neutral"] and berlin["stype"] == "reg"
    cal = espn.calendar(sb)
    assert len(cal) > 200 and cal[0].startswith("2025") and "20260115" in cal


def test_standings_injuries_roster_parsers(monkeypatch):
    c = espn.Client(budget=10, interval=0)
    monkeypatch.setattr(c, "get", lambda url, params=None: load_json("standings_nba_2003.json"))
    groups = espn.standings(c, "nba", 2003)
    assert groups["17"] == {"conference": "East", "division": "Atlantic"} and groups["24"]["division"] == "Midwest"
    monkeypatch.setattr(c, "get", lambda url, params=None: load_json("injuries_wnba.json"))
    inj = espn.injuries(c, "wnba")
    assert inj and all(re.match(r"^\d+$", r[0]) and r[1] for rows in inj.values() for r in rows)
    monkeypatch.setattr(c, "get", lambda url, params=None: load_json("roster_wnba.json"))
    ro = espn.roster(c, "wnba", "20")
    assert ro and all(p["id"] and p["pool"] in ("G", "F", "C") for p in ro)


def test_client_never_raises_on_bad_answers(monkeypatch):
    class R:
        def __init__(self, code, body=None, text="<html>"):
            self.status_code, self._b, self.headers = code, body, {}

        def json(self):
            if self._b is None:
                raise ValueError("not json")
            return self._b

    answers = iter([R(404), R(200, None), R(200, {"ok": 1})])
    monkeypatch.setattr(espn.requests, "get", lambda *a, **k: next(answers))
    c = espn.Client(budget=3, interval=0)
    assert c.get("u") is None and c.get("u") is None and c.get("u") == {"ok": 1}
    assert c.used == 3 and c.failures == 2
    with pytest.raises(espn.BudgetExhausted):
        c.get("u")


def test_clock_and_canon():
    assert espn.clock_s("12:00") == 720 and espn.clock_s("28.6") == 28.6 and espn.clock_s("1:05.5") == 65.5
    assert canon.game_t("nba", 5, 300) == 2880 and canon.game_t("wnba", 4, 0) == 2400 and canon.game_t("wnba", 2, 0, 2003) == 2400
    assert canon.pool("PG") == "G" and canon.pool("G-F") == "F" and canon.pool("C") == "C" and canon.pool(None) is None
    assert canon.stype(5) == "playin" and canon.stype(2, "NBA Cup Championship") == "cup" and canon.stype(2, "NBA All-Star Game") == "allstar"
    # the 2023 NBA and 2021 WNBA finals' notes; knockout rounds before the final still count
    assert canon.stype(2, "NBA In-Season Tournament Championship") == "cup"
    assert canon.stype(2, "WNBA Commissioner's Cup") == "cup"
    assert canon.stype(2, "NBA In-Season Tournament Semifinal") == "reg"
    assert canon.stype(2, "NBA Cup Semifinal") == "reg"
    assert canon.team_label("nba", "25", 2005) == ("Seattle SuperSonics", "SEA") and canon.team_label("nba", "25", 2026)[1] == "OKC"
    assert canon.current_season("nba", __import__("datetime").date(2026, 10, 1)) == 2027
    assert canon.current_season("wnba", __import__("datetime").date(2026, 10, 1)) == 2026


# ── play-by-play on real games ─────────────────────────────────────────────

def test_substitution_participant_order(parsed):
    """'X enters the game for Y' lists X (entering) first: checked against box-score names."""
    raw = parsed["playoff"][0]
    names = {}
    for t in raw["boxscore"]["players"]:
        for a in t["statistics"][0]["athletes"]:
            names[str(a["athlete"]["id"])] = a["athlete"]["displayName"]
    n = 0
    for p in raw["plays"]:
        if p["type"]["id"] == "584":
            pin, pout = (str(x["athlete"]["id"]) for x in p["participants"][:2])
            assert p["text"] == f"{names[pin]} enters the game for {names[pout]}"
            n += 1
    assert n > 50


@pytest.mark.parametrize("name", PBP_GAMES)
def test_points_exact(parsed, name):
    _, g, p, ev, *_ = parsed[name]
    assert pbp.points_check(g, ev)["ok"]


@pytest.mark.parametrize("name", PBP_GAMES)
def test_possessions_balanced(parsed, name):
    _, g, p, ev, *_ = parsed[name]
    n = {g["home"]: 0, g["away"]: 0}
    pts = {g["home"]: 0, g["away"]: 0}
    for x in ev.possessions:
        n[x["team"]] += 1
        pts[x["team"]] += x["pts"]
        assert x["end"] in ("made", "dreb", "tov", "ft", "period", "other")
        assert x["start_kind"] in ("tr", "made", "dead", "oreb", "period")
        assert x["end_t"] >= x["start_t"]
    assert abs(n[g["home"]] - n[g["away"]]) <= 2
    # possessions carry nearly every point (technical free throws by the defence are the exception)
    assert pts[g["home"]] >= g["hs"] - 3 and pts[g["away"]] >= g["as"] - 3
    # and the count is close to the box-score estimate
    for tid in n:
        t = g["box"][tid]["team"]
        est = t["fga"] - t["oreb"] + t["tov"] + 0.44 * t["fta"]
        assert abs(n[tid] - est) < 0.12 * est


@pytest.mark.parametrize("name", PBP_GAMES)
def test_stints_reconcile(parsed, name):
    _, g, p, ev, *_ = parsed[name]
    st = pbp.stints(g, ev)
    rec = pbp.reconcile(g, st)
    assert rec["ok"] and rec["max_err_s"] <= 60, rec
    assert all(len(s["home"]) == 5 and len(s["away"]) == 5 for s in st)
    total = sum(s["t1"] - s["t0"] for s in st)
    assert total == pytest.approx(canon.period_start(ev.league, g["periods"] + 1, ev.season), abs=1)
    assert sum(s["pts_home"] for s in st) == g["hs"] and sum(s["pts_away"] for s in st) == g["as"]
    assert sum(s["poss_home"] + s["poss_away"] for s in st) == len(ev.possessions)
    rows = pbp.stint_rows(g["id"], st)
    assert rows and all(len(r) == len(pbp.STINT_COLS) for r in rows)


def test_event_counts_match_box(parsed):
    for name in PBP_GAMES:
        _, g, p, ev, *_ = parsed[name]
        for tid in (g["home"], g["away"]):
            t = g["box"][tid]["team"]
            evs = [e for e in ev.events if e["team"] == tid]
            assert sum(e["kind"] == "ft" for e in evs) == t["fta"], name
            assert abs(sum(e["kind"] == "shot" for e in evs) - t["fga"]) <= 2, name
            assert abs(sum(e["kind"] == "tov" for e in evs) - t["tov"]) <= 1, name
            assert sum(e["kind"] == "reb" and e.get("off") and bool(e["players"]) for e in evs) == t["oreb"], name


def test_shots_table(parsed):
    n = agree = 0
    for name in PBP_GAMES:
        _, g, p, ev, *_ = parsed[name]
        rows = pbp.shots(g, ev, p["types"])
        assert all(len(r) == len(pbp.SHOT_COLS) for r in rows)
        col = {c: i for i, c in enumerate(pbp.SHOT_COLS)}
        for tid, made_pts in ((g["home"], g["hs"]), (g["away"], g["as"])):
            fg = sum(r[col["value"]] for r in rows if r[col["team"]] == tid and r[col["made"]])
            ftm = g["box"][tid]["team"]["ftm"]
            assert fg + ftm == made_pts
        for r in rows:
            assert r[col["zone"]] in ("rim", "paint", "mid", "corner3", "ab3", "heave", None)
            assert r[col["shot_type"]] in ("dunk", "layup", "tip", "hook", "floater", "jumper", "pullup", "stepback", "fadeaway", "turnaround", "other")
            if r[col["value"]] == 3:
                assert r[col["zone"]] in ("corner3", "ab3", "heave", None)
            else:
                assert r[col["zone"]] in ("rim", "paint", "mid", None)
            if r[col["assisted"]]:
                assert r[col["made"]] and r[col["assister"]] and r[col["assister"]] != r[col["shooter"]]
            if r[col["blocked"]]:
                assert not r[col["made"]]
            if r[col["dist_ft"]] is not None and r[col["x_ft"]] is not None:
                assert -26 <= r[col["x_ft"]] <= 26 and r[col["y_ft"]] >= -6
        q = pbp.shot_quality(ev)
        n += q["n"]
        agree += q["agree"]
        assert sum(r[col["assisted"]] for r in rows) == sum(g["box"][t]["team"]["ast"] for t in g["box"]) or name == "y2018"
        assert any(r[col["putback"]] for r in rows) and any(r[col["transition"]] for r in rows)
    assert agree / n >= 0.99


def test_text_distance_matches_coordinates(parsed):
    """The fitted rim position reproduces ESPN's own 'N-foot' distances."""
    errs = []
    for name in PBP_GAMES:
        _, g, p, ev, *_ = parsed[name]
        for e in ev.events:
            m = re.search(r"(\d+)-foot", e["text"])
            if e["kind"] == "shot" and m and e["x"] is not None:
                errs.append(abs(pbp.shot_geometry(e["x"], e["y"])[2] - int(m.group(1))))
    assert len(errs) > 500 and sum(errs) / len(errs) < 0.6


def test_period_fives_and_clutch(parsed):
    _, g, p, ev, *_ = parsed["ot"]
    assert set(ev.period_fives) == {1, 2, 3, 4, 5}
    rows = pbp.shots(g, ev)
    col = {c: i for i, c in enumerate(pbp.SHOT_COLS)}
    ot = [r for r in rows if r[col["period"]] == 5]
    assert ot and all(2880 <= r[col["t"]] <= 3180 for r in ot)
    assert any(r[col["clutch"]] for r in rows)


def test_wp_mapped(parsed):
    p = parsed["playoff"][2]
    seqs = {str(r[0]) for r in p["plays"]}
    assert len(p["wp"]) > 400 and set(p["wp"]) <= seqs and all(0 <= v <= 1 for v in p["wp"].values())


# ── hand-made edge cases ────────────────────────────────────────────────────

def _opening(b):
    b.jump(1, 720, H, "h5", "a5", "h1")
    return b


def test_and_one(builder):
    b = _opening(builder())
    b.shot(1, 700, H, "h1", True, assist="h2")
    b.foul(1, 700, A, "a1", "shooting")
    b.ft(1, 700, H, "h1", True, 1, 1)
    b.shot(1, 680, A, "a2", False)
    b.reb(1, 678, H, "h3", False)
    b.end_period(1)
    ev = pbp.parse(b.pbp(), b.game())
    first = ev.possessions[0]
    assert first["team"] == H and first["pts"] == 3 and first["end"] == "ft" and first["start_kind"] == "period"
    assert ev.possessions[1]["team"] == A and ev.possessions[1]["start_kind"] == "made" and ev.possessions[1]["end"] == "dreb"
    assert ev.possessions[2]["team"] == H and ev.possessions[2]["start_kind"] == "tr"
    assert pbp.points_check(b.game(), ev)["ok"]


def test_technical_free_throw_keeps_possession(builder):
    b = _opening(builder())
    b.foul(1, 710, A, "a1", "technical")
    b.ft(1, 710, H, "h2", True, kind="technical")
    b.shot(1, 700, H, "h1", False)
    b.reb(1, 698, H, "h4", True)
    b.foul(1, 690, H, "h4", "technical")
    b.ft(1, 690, A, "a2", True, kind="technical")      # the defence's technical: no change of possession
    b.shot(1, 685, H, "h4", True)
    b.end_period(1)
    g = b.game()
    ev = pbp.parse(b.pbp(), g)
    first = ev.possessions[0]
    assert first["team"] == H and first["end"] == "made" and first["pts"] == 3   # 1 technical + 2
    assert pbp.points_check(g, ev)["ok"] and g["hs"] == 3 and g["as"] == 1
    assert len([p for p in ev.possessions if p["team"] == H]) == 1


def test_flagrant_free_throws_then_ball(builder):
    b = _opening(builder())
    b.shot(1, 700, H, "h1", False)
    b.reb(1, 698, A, "a1", False)
    b.foul(1, 690, H, "h2", "flagrant")
    b.ft(1, 690, A, "a1", True, 1, 2, kind="flagrant")
    b.ft(1, 690, A, "a1", True, 2, 2, kind="flagrant")
    b.shot(1, 680, A, "a3", True, pa=3, x=3, y=2)
    b.end_period(1)
    ev = pbp.parse(b.pbp(), b.game())
    a = [p for p in ev.possessions if p["team"] == A]
    assert len(a) == 1 and a[0]["pts"] == 5 and a[0]["end"] == "made" and a[0]["start_kind"] == "tr"
    rows = pbp.shots(b.game(), ev)
    col = {c: i for i, c in enumerate(pbp.SHOT_COLS)}
    three = [r for r in rows if r[col["value"]] == 3][0]
    assert three[col["zone"]] == "corner3" and three[col["margin_before"]] == 2


def test_jump_balls(builder):
    b = _opening(builder())
    b.shot(1, 700, H, "h1", False)
    b.reb(1, 698, H, "h2", True)
    b.jump(1, 690, A, "h2", "a2", "a3")                 # held ball, the defence wins the tip
    b.shot(1, 680, A, "a3", True)
    b.end_period(1)
    ev = pbp.parse(b.pbp(), b.game())
    assert [p["team"] for p in ev.possessions] == [H, A]
    assert ev.possessions[0]["end"] == "other" and ev.possessions[1]["pts"] == 2


def test_overtime_clock_and_lineups(builder):
    b = _opening(builder())
    for per in (1, 2, 3, 4):
        b.shot(per, 600, H, "h1", True)
        b.shot(per, 590, A, "a1", True)
        b.end_period(per)
    b.shot(5, 290, H, "h1", True)
    b.shot(5, 10, A, "a1", True, pa=3, x=25, y=27)
    b.end_period(5)
    g = b.game({**{p: 3180 for p in ["h1", "h2", "h3", "h4", "h5", "a1", "a2", "a3", "a4", "a5"]}})
    ev = pbp.parse(b.pbp(), g)
    st = pbp.stints(g, ev)
    assert st[-1]["t1"] == 3180 and pbp.reconcile(g, st)["max_err_s"] == 0
    rows = pbp.shots(g, ev)
    col = {c: i for i, c in enumerate(pbp.SHOT_COLS)}
    last = rows[-1]
    assert last[col["t"]] == 3170 and last[col["clutch"]] == 1 and last[col["margin_before"]] == -2 and last[col["zone"]] == "ab3"


def test_sub_at_period_break_logged(builder):
    b = _opening(builder())
    b.shot(1, 700, H, "h1", True)
    b.end_period(1)
    b.sub(2, 720, H, "h6", "h1")                        # logged at the new period's opening clock
    b.shot(2, 700, H, "h6", True)
    b.end_period(2)
    g = b.game({"h1": 720, "h6": 720, "h2": 1440, "h3": 1440, "h4": 1440, "h5": 1440, **{f"a{i}": 1440 for i in range(1, 6)}})
    ev = pbp.parse(b.pbp(), g)
    st = pbp.stints(g, ev)
    assert "h6" in st[-1]["home"] and "h1" not in st[-1]["home"] and st[-1]["t0"] == 720
    assert pbp.reconcile(g, st)["max_err_s"] == 0


def test_sub_at_period_break_not_logged(builder):
    """No substitution row: h6 acts in period 2 and h1 is subbed back in later, so the period's
    opening five is inferred as h2-h6."""
    b = _opening(builder())
    b.shot(1, 700, H, "h1", True)
    b.end_period(1)
    b.shot(2, 700, H, "h6", True)
    b.sub(2, 360, H, "h1", "h6")
    b.end_period(2)
    g = b.game({"h1": 1080, "h6": 360, "h2": 1440, "h3": 1440, "h4": 1440, "h5": 1440, **{f"a{i}": 1440 for i in range(1, 6)}})
    ev = pbp.parse(b.pbp(), g)
    assert sorted(ev.period_fives[2][H]) == ["h2", "h3", "h4", "h5", "h6"]
    assert pbp.reconcile(g, pbp.stints(g, ev))["max_err_s"] == 0


def test_missing_substitution_repaired(builder):
    """h7 acts without a logged entry: he goes on and the player next seen being subbed in comes off."""
    b = _opening(builder())
    b.shot(1, 700, H, "h1", True)
    b.shot(1, 600, H, "h7", True)                       # h7 never entered
    b.sub(1, 300, H, "h3", "h7")                        # ... and h3 comes back for him later
    b.end_period(1)
    g = b.game()
    ev = pbp.parse(b.pbp(), g)
    st = pbp.stints(g, ev)
    assert ev.lineup_fixes == 1 and all(len(s["home"]) == 5 for s in st)
    mid = [s for s in st if "h7" in s["home"]][0]
    assert "h3" not in mid["home"]


def test_shot_geometry_zones():
    assert pbp.shot_geometry(25, 0.75)[:3] == (0.0, 0.0, 0.0)
    x, y, d, ang = pbp.shot_geometry(1, 1)
    assert x == -24 and abs(ang) > 80 and pbp.is_three("nba", 2026, x, y)
    assert pbp.zone("nba", 2026, x, y, d, 3) == "corner3"
    x, y, d, _ = pbp.shot_geometry(25, 23.5)
    assert pbp.is_three("nba", 2026, x, y) is False and pbp.is_three("wnba", 2026, x, y) is True
    assert pbp.zone("nba", 2026, 0, 2, 2, 2) == "rim" and pbp.zone("nba", 2026, 3, 9, 9.5, 2) == "paint"
    assert pbp.zone("nba", 2026, 15, 10, 18, 2) == "mid" and pbp.zone("nba", 2026, 0, 60, 60, 3) == "heave"
    assert pbp.shot_type(132, "") == "stepback" and pbp.shot_type(999, "makes floating jumper") == "floater"


# ── stores and scripts ─────────────────────────────────────────────────────

def test_store_roundtrip_and_merge(tmp_path, monkeypatch, parsed):
    monkeypatch.setenv("HARDWOOD_DATA", str(tmp_path / "d"))
    monkeypatch.setenv("HARDWOOD_PBP", str(tmp_path / "p"))
    s = store.load("nba", 2026)
    g = parsed["playoff"][1]
    store.merge_game(s, g)
    skeleton = {**g, "box": {}, "odds": None, "has_pbp": False}
    store.merge_game(s, skeleton)                         # a later scoreboard pass never wipes the box
    assert s["games"][g["id"]]["box"] and s["games"][g["id"]]["odds"] and s["games"][g["id"]]["has_pbp"]
    store.mark(s, g["id"])
    store.save(s)
    s2 = store.load("nba", 2026)
    assert store.fetched(s2, g["id"]) and s2["games"][g["id"]]["hs"] == 90
    store.save_pbp("nba", 2026, parsed["playoff"][2])
    assert store.load_pbp("nba", 2026, g["id"])["plays"][0] == parsed["playoff"][2]["plays"][0]


def test_bb_derive_end_to_end(tmp_path, monkeypatch, parsed):
    monkeypatch.setenv("HARDWOOD_DATA", str(tmp_path / "d"))
    monkeypatch.setenv("HARDWOOD_PBP", str(tmp_path / "p"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import bb_derive
    s = store.load("nba", 2026)
    for k in ("reg", "playoff", "ot", "flagrant"):
        _, g, p, *_ = parsed[k]
        store.merge_game(s, g)
        store.mark(s, g["id"])
        store.save_pbp("nba", 2026, p)
    store.save(s)
    summ = bb_derive.derive_season("nba", 2026)
    assert summ["derived"] == 4 and summ["share_all_within_60s"] == 1.0 and summ["share_points_exact"] == 1.0
    shots = store.load_table("nba", 2026, "shots.json")
    stints = store.load_table("nba", 2026, "stints.json")
    assert shots["cols"] == pbp.SHOT_COLS and len(shots["rows"]) > 600
    assert stints["cols"] == pbp.STINT_COLS and {r[0] for r in stints["rows"]} == {parsed[k][1]["id"] for k in ("reg", "playoff", "ot", "flagrant")}
    mtime = (store.season_dir("nba", 2026) / "shots.json").stat().st_mtime_ns
    # unchanged inputs: nothing rewritten; raw gone (as in CI): rows kept
    for f in (tmp_path / "p").rglob("*.json.gz"):
        f.unlink()
    assert bb_derive.derive_season("nba", 2026)["derived"] == 4
    assert (store.season_dir("nba", 2026) / "shots.json").stat().st_mtime_ns == mtime
    assert len(store.load_table("nba", 2026, "stints.json")["rows"]) == len(stints["rows"])


def test_bb_fetch_skips_other_seasons_and_placeholder_finals():
    """ESPN's NBA 2000 calendar also covered the 1999 season, and NBA 1999-2002 scoreboards carry 0-0
    'final' placeholders; neither may enter a season's store."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import bb_fetch
    ok = {"date": "1999-11-03T00:30:00Z", "status": "post", "hs": 98, "as": 91}
    assert bb_fetch._keep_event("nba", 2000, ok)
    assert not bb_fetch._keep_event("nba", 2000, {**ok, "date": "1999-03-02T00:30:00Z"})     # the 1999 season
    assert not bb_fetch._keep_event("nba", 2000, {**ok, "hs": 0, "as": 0})                   # placeholder
    assert bb_fetch._keep_event("nba", 2000, {**ok, "status": "pre", "hs": 0, "as": 0})       # scheduled 0-0 is fine
    assert bb_fetch._keep_event("wnba", 2026, {**ok, "date": "2026-06-30T23:00:00Z"})
    assert not bb_fetch._keep_event("wnba", 2026, {**ok, "date": "2025-09-12T23:00:00Z"})


def test_take_foul_free_throw_keeps_ball(builder):
    """A lone free throw that is not an and-one (take foul) leaves the ball with the shooting team."""
    b = _opening(builder())
    b.foul(1, 700, A, "a1", "personal")
    b.ft(1, 700, H, "h1", True, 1, 1)
    b.shot(1, 690, H, "h2", True)
    b.end_period(1)
    ev = pbp.parse(b.pbp(), b.game())
    assert [p["team"] for p in ev.possessions] == [H] and ev.possessions[0]["pts"] == 3


def test_action_logged_before_same_clock_sub_out(builder):
    """ESPN sometimes logs a steal after the substitution that took the stealer off at the same clock."""
    b = _opening(builder())
    b.shot(1, 700, H, "h1", True)
    b.sub(1, 600, A, "a6", "a2")
    b.tov(1, 600, H, "h1", steal="a2")                 # a2 stole it before going off
    b.shot(1, 590, A, "a6", True)
    b.end_period(1)
    g = b.game()
    ev = pbp.parse(b.pbp(), g)
    assert ev.lineup_fixes == 0
    st = pbp.stints(g, ev)
    assert "a6" in st[-1]["away"] and "a2" not in st[-1]["away"]
