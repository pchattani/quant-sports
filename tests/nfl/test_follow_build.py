"""oddsmarkets/nfl/analytics/follow_build.py: the Gridiron's follow cards from a synthetic payload tree."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL
from oddsmarkets.nfl.analytics import follow_build as B

NOW = datetime(2026, 11, 20, 16, 0, tzinfo=timezone.utc)
S = 2026
TEAMS = {"KC": ("Kansas City Chiefs", "Chiefs", "AFC West", "#e31837"), "DEN": ("Denver Broncos", "Broncos", "AFC West", "#fb4f14"),
         "LV": ("Las Vegas Raiders", "Raiders", "AFC West", "#000000"), "DAL": ("Dallas Cowboys", "Cowboys", "NFC East", "#003594"),
         "PHI": ("Philadelphia Eagles", "Eagles", "NFC East", "#004c54"), "NYG": ("New York Giants", "Giants", "NFC East", "#0b2265")}
PAIRS = (("KC", "DEN"), ("LV", "DAL"), ("PHI", "NYG"))
SPEC = [{"id": "rating", "label": "Team rating", "dir": "higher", "fmt": "+1", "model": True}, {"id": "off_epa", "label": "Offence EPA", "dir": "higher", "fmt": "+2"},
        {"id": "def_epa", "label": "Defence EPA", "dir": "lower", "fmt": "+2"}, {"id": "off_success", "label": "Success rate", "dir": "higher", "fmt": "pct1"},
        {"id": "st_epa_g", "label": "Special teams", "dir": "higher", "fmt": "+1"}, {"id": "sack_rate_def", "label": "Pass rush (sacks)", "dir": "higher", "fmt": "pct1"},
        {"id": "ed_pass_rate", "label": "Early-down pass rate", "dir": "higher", "fmt": "pct0", "style": True}]


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def tree(tmp: Path, phase: str = "regular", champion: bool = False) -> Path:
    data = tmp / "data"
    games, sched = [], {t: [] for t in TEAMS}

    def add(week: int, t0: datetime, h: str, a: str, final: bool, hs=None, as_=None, p_home=0.5, mkt=None):
        g = {"game_id": f"{S}_{week:02d}_{a}_{h}", "week": week, "gtype": "REG", "kickoff": iso(t0), "home": h, "away": a, "hs": hs, "as": as_,
             "status": "final" if final else "scheduled", "model": {"p_home": p_home}}
        games.append(dict(g, market={"p_home": mkt} if mkt is not None else None))
        sched[h].append(g)
        sched[a].append(g)
    # ten weeks played: KC wins every week as the underdog; the others split; one tie
    for w in range(1, 11):
        t0 = NOW - timedelta(days=7 * (11 - w))
        for h, a in PAIRS:
            if h == "KC":
                add(w, t0, h, a, True, 27, 20, p_home=0.38)
            elif w == 5 and h == "PHI":
                add(w, t0, h, a, True, 17, 17)
            else:
                add(w, t0, h, a, True, *((24, 21) if w % 2 else (14, 28)))
    # a result stamped after the build clock: never read
    add(11, NOW + timedelta(hours=30), "DEN", "KC", True, 40, 0)
    add(12, NOW + timedelta(days=7), "KC", "LV", False, p_home=0.71, mkt=0.68)
    add(13, NOW + timedelta(days=14), "DAL", "PHI", False, p_home=0.55)
    stand = {}
    for t, (nm, sh, dv, col) in TEAMS.items():
        reg = [g for g in sched[t] if g["status"] == "final" and FL._dt(g["kickoff"]) <= NOW]
        w = sum(1 for g in reg if (g["hs"] > g["as"]) == (g["home"] == t) and g["hs"] != g["as"])
        tie = sum(1 for g in reg if g["hs"] == g["as"])
        l = len(reg) - w - tie
        stand.setdefault(dv, []).append({"team": t, "name": nm, "w": w, "l": l, "t": tie, "pct": (w + tie / 2) / max(1, len(reg)), "rating": 6.0 if t == "KC" else 0.0,
                                         "p_playoffs": 0.95 if t == "KC" else 0.4, "p_div": 0.8 if t == "KC" else 0.2, "p_sb": 0.2 if t == "KC" else 0.02,
                                         "magic": {"playoffs": 2 if t == "KC" else 9}, "clinched": {}, "eliminated": {}})
    standings = [{"division": d, "conference": d[:3], "teams": rs} for d, rs in stand.items()]
    vals = {t: {"rating": 6.0 if t == "KC" else 0.5 * i, "off_epa": 0.2 - 0.03 * i, "def_epa": -0.1 + 0.03 * i, "off_success": 0.5 - 0.01 * i,
                "st_epa_g": 1.0 - 0.4 * i, "sack_rate_def": 0.09 - 0.01 * i, "ed_pass_rate": 0.5} for i, t in enumerate(TEAMS)}
    pct = {t: {m["id"]: round(100 - 20 * i) for m in SPEC if not m.get("style")} for i, t in enumerate(TEAMS)}
    # weekly ratings: KC climbs from last to first over the last month
    hist = {t: [[w, (5.0 if w >= 8 else -5.0) if t == "KC" else 0.1 * i] for w in range(1, 11)] for i, t in enumerate(TEAMS)}
    write(data / "index.json", {"ok": True, "season": S, "phase": phase, "teams": {t: {"name": v[0], "colour": v[3], "division": v[2]} for t, v in TEAMS.items()},
                                "playoff_odds": {r["team"]: {k: r[k] for k in ("p_playoffs", "p_div", "p_sb")} for rs in stand.values() for r in rs}})
    write(data / str(S) / "season.json", {"ok": True, "phase": phase, "standings": standings, "sim": {"ok": True, "teams": {}},
                                          "league": {"profile": {"metrics": SPEC}, "teams": {"KC": {"luck": {"d": 3.4}}}, "race": {"KC": {"sos": [2.1, 1, 7]}}}})
    write(data / str(S) / "teams.json", {"ok": True, "teams": {t: {"name": TEAMS[t][0], "short": TEAMS[t][1], "values": vals[t], "pct": pct[t], "history": hist[t],
                                                                   "schedule": sched[t]} for t in TEAMS}})
    write(data / str(S) / "schedule.json", {"ok": True, "games": games})
    cols = ["pid", "name", "team", "pos", "gvar_pg", "q"]
    rows = [[f"{t}-QB", f"QB {t}", t, "QB", 5.0 if t == "KC" else 1.0 + 0.1 * i, 1] for i, t in enumerate(TEAMS)]
    rows += [[f"{t}-WR", f"WR {t}", t, "WR", 2.0, 1] for t in TEAMS] + [[f"{t}-X", f"Unq {t}", t, "RB", 9.0, 0] for t in TEAMS]
    write(data / str(S) / "value.json", {"ok": True, "cols": cols, "rows": rows})
    write(data / str(S - 1) / "season.json", {"ok": True, "standings": [{"division": "x", "teams": [{"team": t, "w": 3, "l": 14} for t in TEAMS]}]})
    write(data / "race_log.json", {str(S): {"p_playoffs": {(NOW - timedelta(days=8)).date().isoformat(): {"KC": 0.60},
                                                          (NOW - timedelta(days=1)).date().isoformat(): {"KC": 0.95},
                                                          (NOW + timedelta(days=2)).date().isoformat(): {"KC": 0.10}}}})
    if champion:
        write(data / "history.json", {"champions": {"seasons": [{"season": S, "sb": ["KC", "PHI", 31, 17]}]}})
    return data


def cards(data: Path) -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (data / "follow" / "team").glob("*.json")}


def test_a_card_for_every_team_under_the_ceiling(tmp_path):
    data = tree(tmp_path)
    s = B.build(data, NOW)
    cs = cards(data)
    assert s["n"] == len(TEAMS) and set(cs) == set(TEAMS)
    for t, c in cs.items():
        assert c["k"] == f"gridiron:team:{t}" and c["sport"] == "nfl" and c["team"]["href"] == f"#/team/{t}"
        assert FL.card_bytes(c) <= FL.MAX_BYTES and c["phase"] == "season"
        assert 1 <= len(c.get("facts") or []) <= FL.MAX_FACTS
        assert len({f["kind"] for f in c["facts"]}) == len(c["facts"])


def test_the_in_season_card(tmp_path):
    data = tree(tmp_path)
    B.build(data, NOW)
    c = cards(data)["KC"]
    assert c["now"]["record"] == "10–0" and c["now"]["form"] == "WWWWW" and c["now"]["streak"] == "W10"
    assert c["now"]["standing"]["pos"] == 1 and c["now"]["rating"]["rank"] == 1
    assert [x["key"] for x in c["chances"]] == ["p_sb", "p_div", "p_playoffs"]
    assert abs(c["chances"][-1]["d7"] - 0.35) < 1e-6
    # the 40-0 loss after the clock is never the last result; the next game carries ours and the market's chance
    assert c["last"]["score"] == [27, 20] and c["last"]["upset"] is True
    assert c["next"][0]["opp"]["abbr"] == "LV" and c["next"][0]["p"] == 0.71 and c["next"][0]["mkt"] == 0.68
    assert c["next"][0]["comp"] == "Week 12"
    # the profile comes from teams.json pct; the style metric is left out
    ids = {r["id"] for r in c["profile"]["strong"] + c["profile"]["weak"]}
    assert "ed_pass_rate" not in ids and len(c["profile"]["strong"]) == 3
    # top players: qualified only, by value per game
    assert [p["name"] for p in c["players"]] == ["QB KC", "WR KC"] and c["players"][0]["metric"] == "value/game"
    kinds = {f["kind"] for f in c["facts"]}
    assert {"streak", "rating_move"} & kinds
    fx = {f["kind"]: f["text"] for f in c["facts"]}
    if "rating_move" in fx:
        assert "up" in fx["rating_move"]


def test_a_tie_and_the_magic_number(tmp_path):
    data = tree(tmp_path)
    B.build(data, NOW)
    cs = cards(data)
    assert cs["PHI"]["now"]["record"].count("–") == 2          # 'w–l–t' with the tie
    cands = FL.candidates({"clinch": {"magic": 2, "what": "a playoff place"}}, NOW)
    assert cands and cands[0]["kind"] == "clinch"


def test_no_look_ahead_on_an_earlier_clock(tmp_path):
    data = tree(tmp_path)
    early = NOW - timedelta(days=20)
    B.build(data, early)
    c = cards(data)["KC"]
    assert FL._dt(c["last"]["start"]) <= early
    assert c["chances"][-1].get("d7") is None


def test_offseason_champion(tmp_path):
    data = tree(tmp_path, phase="offseason", champion=True)
    B.build(data, NOW + timedelta(days=90))
    c = cards(data)["KC"]
    assert c["phase"] == "offseason" and c["champion"]["event"] == "Super Bowl" and "Eagles" in c["line"]
    assert "form" not in c["now"] and not c.get("chances") and not c.get("next")
    assert not {f["kind"] for f in c["facts"]} & FL.LIVE_KINDS
    other = cards(data)["DEN"]
    assert "champion" not in other and other["line"].startswith("Season over")
