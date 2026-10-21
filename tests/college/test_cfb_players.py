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


def test_value_and_careers(built):
    v = _load(built["out"] / "2024" / "value.json")
    assert v["leaders"] and {"id", "name", "team", "pos", "value", "value_pg", "pctl", "why"} <= set(v["leaders"][0])
    assert "QB" in v["by_position"]
    pfile = next((built["out"] / "players").glob("*.json"))
    car = _load(pfile)
    assert car["ok"] and car["seasons"] and {"season", "team", "gp", "value"} <= set(car["seasons"][0])
    cal = _load(built["out"] / "calibration.json")
    assert cal["summary"]["vs_close"]["n"] > 0 and cal["committee"]["n_seasons"] >= 1
