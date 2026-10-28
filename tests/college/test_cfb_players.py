"""College football player attribution, value, fantasy scoring and the payload writer (synthetic world)."""
import json

import pandas as pd
import pytest

from oddsmarkets.college.football import build, fantasy, players, synthetic


def test_parse_play_text_styles():
    p = players.parse("(13:36) Shotgun #5 D.Moore pass complete short right to #22 J.Harris caught at Ore35, for 12 yards")
    assert p["passer"] == "D.Moore|5" and p["target"] == "J.Harris|22" and p["rusher"] is None
    p = players.parse("Jaxson Dart pass complete to Cayden Lee for 28 yds to the MISS 48")
    assert p["passer"] == "Jaxson Dart" and p["target"] == "Cayden Lee"
    p = players.parse("Johntay Cook Ii 3 Yd pass from Steve Angeli (Tripp Woody Kick)")
    assert p["passer"] == "Steve Angeli" and p["target"] == "Johntay Cook Ii"
    assert players.parse("Jordan James run for 8 yds")["rusher"] == "Jordan James"
    assert players.parse("(02:17) Shotgun #11 C.Beck sacked for loss of 7 yards")["passer"] == "C.Beck|11"
    assert players.parse("(07:30) No Huddle #9 E.Williams pass incomplete deep right thrown to RICE20")["target"] is None


def test_name_keys():
    assert players.name_key("M.Fletcher Jr.") == players.name_key("Mark Fletcher Jr.") == ("m", "fletcher")
    assert players.name_key("M.Van Buren Jr.") == ("m", "van buren")
    assert players.name_key("TEAM") is None


def test_def_and_st_points():
    df = pd.DataFrame([{c: 0.0 for c in players.STAT_COLS}])
    df.loc[0, ["tkl", "solo", "sacks", "tfl"]] = [6, 4, 1, 1]
    assert players.def_points(df).iloc[0] == pytest.approx(0.25 * 4 + 0.12 * 2 + 0.9 + 1.0)
    df2 = pd.DataFrame([{c: 0.0 for c in players.STAT_COLS}])
    df2.loc[0, ["fgm", "fga", "xpm", "xpa"]] = [2, 2, 3, 3]
    assert players.st_points(df2).iloc[0] == pytest.approx(3 * (2 - 1.56) + (3 - 2.88))


def test_fantasy_scoring():
    row = {c: 0.0 for c in players.STAT_COLS}
    row.update({"pass_yds": 250, "pass_td": 2, "pass_int": 1, "rec": 5, "rec_yds": 50})
    df = pd.DataFrame([row])
    assert fantasy.points(df, "std").iloc[0] == pytest.approx(10 + 8 - 2 + 5)
    assert fantasy.points(df, "ppr").iloc[0] == pytest.approx(10 + 8 - 2 + 5 + 5)
    assert fantasy.points(df, "half").iloc[0] == pytest.approx(10 + 8 - 2 + 5 + 2.5)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("cfbbuild")
    with pytest.MonkeyPatch.context() as mp:
        for k in ("CAMPUS_STORES", "CAMPUS_RAW", "CAMPUS_CACHE", "CAMPUS_DATA"):
            mp.setenv(k, str(root / k.lower()))
        build.reset()
        synthetic.make_world(root, seasons=(2022, 2023, 2024))
        out = root / "campus_data"
        s24 = build.build(2024, out, full=True, sims=1000, markets=False, current=2024)
        s23 = build.build(2023, out, full=True, sims=1000, markets=False, current=2024)
        lv = build.build_level(out, [2022, 2023, 2024], 2024, markets=False, sims=1000)
        yield {"root": root, "out": out / "cfb", "s24": s24, "s23": s23, "lv": lv}
        build.reset()


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_build_writes_every_payload(built):
    d = built["out"] / "2024"
    for name in ("season", "schedule", "cfp", "teams", "players", "value", "moves", "fantasy", "lab_players", "lab_teams"):
        obj = _load(d / f"{name}.json")
        assert obj.get("ok") is True, (name, obj.get("reason"))
    assert len(list((d / "teams").glob("*.json"))) == 24
    assert len(list((d / "games").glob("*.json"))) > 50
    for name in ("calibration", "history", "markets"):
        assert _load(built["out"] / f"{name}.json").get("ok") is True, name
    assert built["lv"]["players"] > 0 and len(list((built["out"] / "players").glob("*.json"))) == built["lv"]["players"]


def test_season_payload_shapes(built):
    s = _load(built["out"] / "2024" / "season.json")
    t = next(iter(s["ratings"]))
    assert {"rating", "off", "def", "se", "rank", "games", "epa_off", "epa_def", "sr_off", "sr_def", "pts_rating", "sos", "sos_rank"} <= set(s["ratings"][t])
    assert s["sim"]["n_sims"] == 1000
    st = s["sim"]["teams"][t]
    assert {"exp_w", "exp_l", "w_dist", "p_bowl", "p_conf_game", "p_conf", "p_cfp", "p_bye", "p_round", "seed_dist", "p_title", "next"} <= set(st)
    assert set(st["p_round"]) == {"qf", "sf", "final", "title"}
    assert s["format"]["cfp"]["teams"] == 12
    sch = _load(built["out"] / "2024" / "schedule.json")["games"]
    c = sch[0]
    assert {"id", "season", "date", "status", "home", "away", "hs", "as", "hr", "ar", "model", "market", "result"} <= set(c)
    fin = [c for c in sch if c["status"] == "post"]
    assert fin and fin[0]["result"]["cover"] in ("home", "away", "push", None)


def test_cfp_and_team_pages(built):
    c = _load(built["out"] / "2024" / "cfp.json")
    assert c["projected_bracket"]["seeds"] and len(c["projected_bracket"]["seeds"]) == 12
    assert c["committee_proxy"] and {"rank", "team", "score", "p_in", "record"} <= set(c["committee_proxy"][0])
    c23 = _load(built["out"] / "2023" / "cfp.json")
    assert c23["actual"]["bracket"]["games"] and c23["format"]["teams"] == 4
    assert abs(sum(v["p_title"] for v in c23["odds"].values()) - 1) < 0.01
    tid = next(p.stem for p in (built["out"] / "2024" / "teams").glob("*.json"))
    tp = _load(built["out"] / "2024" / "teams" / f"{tid}.json")
    assert tp["ok"] and len(tp["strengths"]) == 3 and len(tp["needs"]) == 3 and tp["schedule"]
    assert {"unit", "grade", "pctl", "value", "evidence"} <= set(tp["units"][0])


def test_game_page(built):
    g = next(p for p in sorted((built["out"] / "2024" / "games").glob("*.json")) if _load(p)["status"] == "post")
    obj = _load(g)
    assert obj["ok"] and obj["pregame"]["model"]["p_home"] is not None
    assert obj["box"] and obj["flow"] and obj["wp"]["model"]
    assert obj["epa"] and all("epa_play" in v for v in obj["epa"].values())


def test_players_rate_fields(built):
    """Metrics spec (docs/_design/metrics/college.json): rate fields by position, `qualified_rate`, rate percentiles
    within the position among rate-qualified players only (100 = best, lower-is-better rates reversed)."""
    from oddsmarkets.college.football import players as FP
    cat = _load(built["out"] / "2024" / "players.json")
    keys = {m["key"] for m in cat["metrics"]}
    assert keys >= {k for ks in FP.RATE_FIELDS.values() for k in ks}
    assert set(cat["min_floor"]["rate"]) >= {"QB", "RB", "WR", "DL", "K", "P"}
    pl = cat["players"]
    qbs = [p for p in pl.values() if p["pos"] == "QB" and p["qualified_rate"]]
    assert qbs and all("epa_db" in p["values"] and "epa_db" in p["pct_pos"] for p in qbs)
    assert all("epa_db" not in p["pct"] for p in qbs)
    for p in pl.values():
        for k in FP.RATE_FIELDS.get(p["pos"], []):
            if k in p["pct_pos"]:
                assert p["qualified_rate"]
    lo = [p for p in qbs if p["values"].get("int_rate") is not None]
    if len(lo) >= 2:
        a, b = min(lo, key=lambda p: p["values"]["int_rate"]), max(lo, key=lambda p: p["values"]["int_rate"])
        assert a["pct_pos"]["int_rate"] >= b["pct_pos"]["int_rate"]
    for p in pl.values():
        v = p["values"]
        for k in ("cmp_pct", "sr_db", "tgt_share", "rush_share", "fg_pct"):
            if v.get(k) is not None:
                assert 0 <= v[k] <= 1.0001, (k, v[k])


def test_value_and_careers(built):
    v = _load(built["out"] / "2024" / "value.json")
    assert v["leaders"] and {"id", "name", "team", "pos", "value", "value_pg", "pctl", "why"} <= set(v["leaders"][0])
    assert "QB" in v["by_position"]
    pfile = next((built["out"] / "players").glob("*.json"))
    car = _load(pfile)
    assert car["ok"] and car["seasons"] and {"season", "team", "gp", "value"} <= set(car["seasons"][0])
    cal = _load(built["out"] / "calibration.json")
    assert cal["summary"]["vs_close"]["n"] > 0 and cal["committee"]["n_seasons"] >= 1


def test_box_frame_drops_espn_team_rows():
    """ESPN's box carries a team row (negative id, name " Team") for team rushes and punts: never a player."""
    st = {"games": {"1": {"status": "post", "home": "10", "away": "20", "date": "2026-09-05T16:00:00Z",
                          "stype": "reg", "week": 1,
                          "box": {"10": {"players": {"rushing": {
                              "cols": ["rushing_attempts", "rushing_yards", "yards_per_rush_attempt", "rushing_touchdowns",
                                       "long_rushing"],
                              "rows": [["501", 12, 80, 6.7, 1, 30], ["-103071", 3, -5, -1.7, 0, 0]]}}}}}}}
    df = players.box_frame(2026, st)
    assert df["pid"].tolist() == ["501"]
    assert df.loc[0, "rush_yds"] == 80


def test_conference_record_excludes_the_title_game():
    """ESPN and the conferences count a championship game in the overall record only (Indiana 2025: 9-0 Big Ten)."""
    gf = pd.DataFrame([
        {"final": True, "home": "1", "away": "2", "hs": 30, "as": 20, "neutral": False, "conf_game": True, "stype": "reg"},
        {"final": True, "home": "1", "away": "2", "hs": 24, "as": 21, "neutral": True, "conf_game": True, "stype": "conf"},
        {"final": True, "home": "3", "away": "1", "hs": 10, "as": 35, "neutral": False, "conf_game": False, "stype": "reg"}])
    tm = {"1": {"conference": "5"}, "2": {"conference": "5"}, "3": {"conference": "8"}}
    out = build._standings({"st": {}, "gf": gf, "tm": tm, "ratings": {}, "mem": ["1", "2", "3"]})
    one = next(r for r in out["5"] if r["team"] == "1")
    assert (one["w"], one["l"], one["conf_w"], one["conf_l"]) == (3, 0, 1, 0)
    two = next(r for r in out["5"] if r["team"] == "2")
    assert (two["w"], two["l"], two["conf_w"], two["conf_l"]) == (0, 2, 0, 1)


def test_play_flags_and_credit_rates():
    """Play-credit rates (metrics spec): sacks, completions, yards per role, 20+ / 10+ explosives, stuffs."""
    pa = pd.DataFrame([
        dict(gid="g", kind="pass", type_id=24, yards=25, text="A B pass complete to C D for 25 yds", passer_id="qb", target_id="wr",
             rusher_id=None),
        dict(gid="g", kind="pass", type_id=3, yards=0, text="A B pass incomplete to C D", passer_id="qb", target_id="wr", rusher_id=None),
        dict(gid="g", kind="pass", type_id=7, yards=-8, text="A B sacked by X Y for a loss of 8 yards", passer_id="qb", target_id=None,
             rusher_id=None),
        dict(gid="g", kind="pass", type_id=26, yards=12, text="A B pass intercepted Z return for 12 yds", passer_id="qb", target_id="wr",
             rusher_id=None),
        dict(gid="g", kind="rush", type_id=5, yards=-2, text="R B run for a loss of 2", passer_id=None, target_id=None, rusher_id="rb"),
        dict(gid="g", kind="rush", type_id=5, yards=14, text="R B run for 14 yds", passer_id=None, target_id=None, rusher_id="rb"),
    ])
    pa = pa.assign(scrim=True, garbage=False, epa=0.1, success=1.0)
    c = players.play_credit(pa).set_index("pid")
    assert (c.loc["qb", "db_n"], c.loc["qb", "db_sack"], c.loc["qb", "db_cmp"], c.loc["qb", "db_expl"]) == (4, 1, 1, 1)
    assert c.loc["qb", "db_yds"] == 25 - 8                       # the interception's return yards are not his
    assert (c.loc["wr", "tg_n"], c.loc["wr", "tg_cmp"], c.loc["wr", "tg_yds"], c.loc["wr", "tg_expl"]) == (3, 1, 25, 1)
    assert (c.loc["rb", "ru_n"], c.loc["rb", "ru_stuff"], c.loc["rb", "ru_expl"], c.loc["rb", "ru_yds"]) == (2, 1, 1, 12)


def test_new_rate_fields_and_box_count_direction(built):
    """sack_rate ... expl_tgt reach players.json with lower-is-better reversed; box counts with lower=True (pass_int)
    rank so that 100 = best (fewest interceptions)."""
    cat = _load(built["out"] / "2024" / "players.json")
    keys = {m["key"]: m for m in cat["metrics"]}
    for k in ("sack_rate", "expl_pass", "ypd", "qb_rush_epa", "expl_rush", "stuff_rate", "ypt", "catch_rate", "expl_tgt",
              "fga_pg", "fg_long"):
        assert k in keys, k
    assert keys["sack_rate"]["lower"] and keys["stuff_rate"]["lower"]
    pl = cat["players"]
    wrs = [p for p in pl.values() if p["pos"] == "WR" and p["values"].get("catch_rate") is not None]
    assert wrs and all(0 <= p["values"]["catch_rate"] <= 1 for p in wrs)
    assert any("ypt" in p["pct_pos"] for p in wrs)
    qbs = [p for p in pl.values() if p["pos"] == "QB" and "pass_int" in p["pct_pos"]]
    if len(qbs) >= 2:
        a = min(qbs, key=lambda p: p["values"]["pass_int"])
        b = max(qbs, key=lambda p: p["values"]["pass_int"])
        if a["values"]["pass_int"] < b["values"]["pass_int"]:
            assert a["pct_pos"]["pass_int"] > b["pct_pos"]["pass_int"]
            assert a["pct"]["pass_int"] > b["pct"]["pass_int"]


def test_team_adjusted_pass_and_rush_epa(built):
    """teams.json gains opponent-adjusted pass and rush EPA, offence and defence (the EPA ridge split by play type);
    the raw pass_epa / rush_epa stay as they were."""
    import numpy as np
    t = _load(built["out"] / "2024" / "teams.json")
    meta = {m["key"]: m for m in t["metrics"]}
    assert not meta["off_pass_epa"]["lower"] and meta["def_pass_epa"]["lower"] and meta["def_rush_epa"]["lower"]
    rows = [r["values"] for r in t["teams"].values()]
    for k in ("off_pass_epa", "def_pass_epa", "off_rush_epa", "def_rush_epa", "pass_epa", "rush_epa"):
        assert all(isinstance(v.get(k), float) for v in rows), k
    raw = np.array([v["pass_epa"] for v in rows])
    adj = np.array([v["off_pass_epa"] for v in rows])
    assert np.corrcoef(raw, adj)[0, 1] > 0.5
    best = max(t["teams"].values(), key=lambda r: r["values"]["off_pass_epa"])
    assert best["pct"]["off_pass_epa"] == 100
    low = min(t["teams"].values(), key=lambda r: r["values"]["def_pass_epa"])
    assert low["pct"]["def_pass_epa"] == 100                     # fewest allowed = best


def test_career_similar_players_follow_the_spec(built):
    """players/<pid>.json similar (CFB): same position, rate-qualified player-seasons, never the player, nearest first."""
    seen = 0
    for f in (built["out"] / "players").glob("*.json"):
        c = _load(f)
        sim = c.get("similar") or []
        if not sim:
            continue
        seen += 1
        assert len(sim) <= 5 and all(s["id"] != c["id"] for s in sim)
        assert all({"id", "name", "team", "season", "distance"} <= set(s) for s in sim)
        d = [s["distance"] for s in sim]
        assert d == sorted(d)
        f2 = built["out"] / str(sim[0]["season"]) / "players.json"
        nb = _load(f2)["players"].get(sim[0]["id"]) if f2.exists() else None
        if nb:
            assert nb["qualified_rate"] and nb["pos"] == c["seasons"][-1].get("pos", nb["pos"])
    assert seen > 0


def test_career_files_carry_the_jersey_number(built):
    """The player hero's outlined number: players/<pid>.json `number` from the store's ESPN roster `jersey`."""
    files = list((built["out"] / "players").glob("*.json"))
    assert files
    nums = [_load(f).get("number") for f in files]
    assert all(n is None or (isinstance(n, str) and n.isdigit() and len(n) <= 2) for n in nums)
    assert any(n is not None for n in nums)


def test_lab_rows_carry_the_spec_minimums(built):
    """The Lab's "Compare within: Position" ranks qualified players of the spec group: lab_players.json rows carry the
    same `qualified` and `qualified_rate` flags as players.json."""
    lab = _load(built["out"] / "2024" / "lab_players.json")
    cat = _load(built["out"] / "2024" / "players.json")["players"]
    f = lab["fields"]
    assert f[-2:] == ["qualified", "qualified_rate"]
    iq, ir, ii = f.index("qualified"), f.index("qualified_rate"), f.index("id")
    assert lab["rows"] and all(isinstance(r[iq], bool) and isinstance(r[ir], bool) for r in lab["rows"])
    hit = [r for r in lab["rows"] if str(r[ii]) in cat]
    assert hit and all(r[iq] == cat[str(r[ii])]["qualified"] and r[ir] == cat[str(r[ii])]["qualified_rate"] for r in hit)
    assert any(r[ir] for r in lab["rows"])
