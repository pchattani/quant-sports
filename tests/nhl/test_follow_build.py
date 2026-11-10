"""oddsmarkets/nhl/analytics/follow_build.py: the Rink's follow cards from a synthetic payload tree."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL
from oddsmarkets.nhl.analytics import follow_build as B

NOW = datetime(2026, 11, 20, 16, 0, tzinfo=timezone.utc)
S = 20262027
TEAMS = {"AAA": ("Alpha Maple Leafs", "Atlantic", "#00205b"), "BBB": ("Beta Canadiens", "Atlantic", "#af1e2d"),
         "CCC": ("Gamma Bruins", "Atlantic", "#ffb81c"), "DDD": ("Delta Oilers", "Pacific", "#041e42"),
         "EEE": ("Echo Flames", "Pacific", "#c8102e"), "FFF": ("Foxtrot Kraken", "Pacific", "#001628")}
PAIRS = (("AAA", "BBB"), ("CCC", "DDD"), ("EEE", "FFF"))


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def tree(tmp: Path, phase: str = "regular") -> Path:
    data = tmp / "data"
    games, sched = [], {t: [] for t in TEAMS}
    gid = 2026020000

    def add(t0: datetime, h: str, a: str, final: bool, hs=None, as_=None, ot=False, p_home=0.5, mkt=None):
        nonlocal gid
        gid += 1
        games.append({"game_id": str(gid), "date": t0.date().isoformat(), "start": iso(t0), "status": "final" if final else "scheduled", "home": h, "away": a})
        for t, home in ((h, True), (a, False)):
            gf, ga = (hs, as_) if home else (as_, hs)
            res = None
            if final:
                res = "W" if gf > ga else ("OTL" if ot else "L")
            sched[t].append({"game_id": str(gid), "date": t0.date().isoformat(), "opp": a if home else h, "home": home, "status": "final" if final else "scheduled",
                             "gf": gf, "ga": ga, "result": res, "p_win": p_home if home else round(1 - p_home, 4),
                             "p_market": (mkt if home else round(1 - mkt, 4)) if mkt is not None else None})
    # 20 days of results: AAA wins every game as the underdog (an upset each night); the others split
    for d in range(20, 0, -1):
        t0 = NOW - timedelta(days=d, hours=-4)
        for h, a in PAIRS:
            if h == "AAA":
                add(t0, h, a, True, 4, 1, p_home=0.35)
            else:
                add(t0, h, a, True, *((3, 2) if d % 2 else (2, 3)), ot=bool(d % 4 == 0))
    # a result stamped after the build clock (a later rebuild's data in the tree): never read
    add(NOW + timedelta(days=1), "BBB", "AAA", True, 9, 0)
    # one game started an hour ago (not "next"), then three to come
    add(NOW - timedelta(hours=1), "DDD", "AAA", False)
    for k in range(3):
        add(NOW + timedelta(days=k + 1, hours=3), "AAA", "CCC", False, p_home=0.62, mkt=0.6)
    rows, divs = [], {}
    for t, (nm, dv, col) in TEAMS.items():
        w = sum(1 for g in sched[t] if g["result"] == "W" and g["date"] <= NOW.date().isoformat())
        l = sum(1 for g in sched[t] if g["result"] == "L" and g["date"] <= NOW.date().isoformat())
        otl = sum(1 for g in sched[t] if g["result"] == "OTL" and g["date"] <= NOW.date().isoformat())
        rows.append({"team": t, "name": nm, "division": dv, "conference": "Eastern" if dv == "Atlantic" else "Western", "gp": w + l + otl, "w": w, "l": l, "otl": otl,
                     "pts": 2 * w + otl, "p_pct": (2 * w + otl) / (2 * (w + l + otl)), "gf": 60, "ga": 40, "rating": 0.6 if t == "AAA" else 0.0, "clinch": None,
                     "p_playoffs": 0.97 if t == "AAA" else 0.4, "p_cup": 0.2 if t == "AAA" else 0.03})
        divs.setdefault(dv, []).append(t)
    divs = [{"conference": "Eastern" if d == "Atlantic" else "Western", "division": d, "teams": sorted(ts, key=lambda x: 0 if x == "AAA" else 1)} for d, ts in divs.items()]
    units = {t: {"rating": 0.6 if t == "AAA" else 0.05 * i, "xgf_pct5": 0.58 if t == "AAA" else 0.5 - 0.01 * i, "cf_pct5": 0.55 - 0.01 * i, "off5": 2.9 - 0.1 * i,
                 "def5": 2.2 + 0.1 * i, "pp": 8.0 - i, "pk": 6.0 + i, "pp_pct": 0.25 - 0.01 * i, "pk_pct": 0.85 - 0.01 * i, "goalie": 0.3 - 0.1 * i, "gd_g": 1.0 - 0.2 * i}
             for i, t in enumerate(TEAMS)}
    write(data / "index.json", {"ok": True, "season": S, "phase": phase, "teams": {t: {"name": v[0], "colour": v[2], "division": v[1]} for t, v in TEAMS.items()},
                                "playoff_odds": {r["team"]: {"p_playoffs": r["p_playoffs"], "p_cup": r["p_cup"]} for r in rows}})
    write(data / str(S) / "season.json", {"ok": True, "phase": phase, "standings": {"rows": rows, "divisions": divs},
                                          "sim": {"ok": True, "teams": {r["team"]: {"p_playoffs": r["p_playoffs"], "p_cup": r["p_cup"]} for r in rows}},
                                          "league": {"profile": {"metrics": []}, "teams": {"AAA": {"luck": {"d": 4.2}}}, "race": {"AAA": {"sos": [0.2, 1, 60]}}}})
    write(data / str(S) / "teams.json", {"ok": True, "teams": {t: {"name": TEAMS[t][0], "units": units[t], "schedule": sched[t]} for t in TEAMS}})
    write(data / str(S) / "schedule.json", {"ok": True, "games": games})
    sk = {f"{t}1": {"name": f"Ace {t}", "team": t, "pos": "C", "toi": 300.0, "values": {"gar_60": 0.9 if t == "AAA" else 0.1 * i}} for i, t in enumerate(TEAMS)}
    sk.update({f"{t}2": {"name": f"Depth {t}", "team": t, "pos": "D", "toi": 40.0, "values": {"gar_60": 5.0}} for t in TEAMS})     # under the minutes floor
    gk = {f"{t}9": {"name": f"Wall {t}", "team": t, "pos": "G", "gp": 10, "values": {"gsax": 6.0 if t == "AAA" else -1.0 + i}} for i, t in enumerate(TEAMS)}
    write(data / str(S) / "skaters.json", {"ok": True, "players": sk})
    write(data / str(S) / "goalies.json", {"ok": True, "players": gk})
    write(data / str(S - 10001) / "season.json", {"ok": True, "standings": {"rows": [{"team": t, "w": 5, "l": 10, "otl": 5} for t in TEAMS]}})
    write(data / "race_log.json", {str(S): {"p_playoffs": {(NOW - timedelta(days=8)).date().isoformat(): {"AAA": 0.70},
                                                          (NOW - timedelta(days=1)).date().isoformat(): {"AAA": 0.97},
                                                          (NOW + timedelta(days=2)).date().isoformat(): {"AAA": 0.10}}}})
    return data


def cards(data: Path) -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (data / "follow" / "team").glob("*.json")}


def test_a_card_for_every_team_under_the_ceiling(tmp_path):
    data = tree(tmp_path)
    s = B.build(data, NOW)
    cs = cards(data)
    assert s["n"] == len(TEAMS) and set(cs) == set(TEAMS) and s["ids"] == sorted(TEAMS)
    for t, c in cs.items():
        assert c["k"] == f"rink:team:{t}" and c["sport"] == "hockey" and c["team"]["href"] == f"#/team/{t}"
        assert FL.card_bytes(c) <= FL.MAX_BYTES and c["phase"] == "season"
        assert 1 <= len(c.get("facts") or []) <= FL.MAX_FACTS
        assert len({f["kind"] for f in c["facts"]}) == len(c["facts"])
    assert s["max"] <= FL.MAX_BYTES


def test_the_in_season_card(tmp_path):
    data = tree(tmp_path)
    B.build(data, NOW)
    c = cards(data)["AAA"]
    # record, form, streak, the division place, the rating rank
    assert c["now"]["record"] == "20–0–0" and c["now"]["form"] == "WWWWW" and c["now"]["streak"] == "W20"
    assert c["now"]["standing"]["pos"] == 1 and "Atlantic" in c["now"]["standing"]["text"]
    assert c["now"]["rating"]["rank"] == 1
    # chances, the headline (the last) is the playoff chance, with the 7-day change from the race log
    assert [x["key"] for x in c["chances"]] == ["p_cup", "p_playoffs"]
    assert abs(c["chances"][-1]["d7"] - 0.27) < 1e-6
    # next games: never the one already started, never past the build clock; with ours and the market's chance
    assert len(c["next"]) == 3 and all(FL._dt(n["start"]) > NOW for n in c["next"])
    assert c["next"][0]["p"] == 0.62 and c["next"][0]["mkt"] == 0.6 and c["next"][0]["opp"]["abbr"] == "CCC"
    # the last result: the frozen pre-game chance, an upset at 35%; the 9-0 loss after the clock is not read
    assert c["last"]["res"] == "W" and c["last"]["score"] == [4, 1] and c["last"]["upset"] is True
    # the profile: percentiles computed from teams.json units (3 strengths, 2 weaknesses)
    assert len(c["profile"]["strong"]) == 3 and len(c["profile"]["weak"]) == 2
    assert all(0 <= r["pct"] <= 100 for r in c["profile"]["strong"] + c["profile"]["weak"])
    # top players: GAR per 60 above the minutes floor, GSAx for goalies
    names = [p["name"] for p in c["players"]]
    assert "Depth AAA" not in names and set(names) == {"Ace AAA", "Wall AAA"}
    assert {p["metric"] for p in c["players"]} == {"GAR/60", "GSAx"}
    kinds = {f["kind"] for f in c["facts"]}
    assert "streak" in kinds and "swing" in kinds or "best_record" in kinds
    # the swing fact names the chance as the card does ("Stanley Cup", the engine keeps inner capitals since 1 Nov 2026)
    assert all(f["text"].startswith(("Playoff chance", "Stanley Cup chance")) for f in c["facts"] if f["kind"] == "swing")
    assert [x["label"] for x in c["chances"]] == ["Stanley Cup", "Playoff"]


def test_an_overtime_loss_is_its_own_letter(tmp_path):
    data = tree(tmp_path)
    B.build(data, NOW)
    cs = cards(data)
    assert any("O" in (c["now"].get("form") or "") for c in cs.values())
    otl_rec = cs["CCC"]["now"]["record"].split("–")
    assert len(otl_rec) == 3


def test_no_look_ahead_on_an_earlier_clock(tmp_path):
    data = tree(tmp_path)
    early = NOW - timedelta(days=10)
    B.build(data, early)
    c = cards(data)["AAA"]
    assert FL._dt(c["last"]["start"]) <= early
    assert all(FL._dt(n["start"]) > early for n in c["next"])
    # the race log point after the clock (0.10) is never the "now" of the 7-day change
    assert c["chances"][-1].get("d7") is None


def test_offseason_card_drops_form_and_chances(tmp_path):
    data = tree(tmp_path, phase="offseason")
    B.build(data, NOW + timedelta(days=30))
    c = cards(data)["AAA"]
    assert c["phase"] == "offseason" and "form" not in c["now"] and not c.get("chances") and not c.get("next")
    assert c["next_note"].startswith("Season over") and c["line"].startswith("Season over")
    assert not {f["kind"] for f in c["facts"]} & FL.LIVE_KINDS


def test_prune_removes_a_team_that_left(tmp_path):
    data = tree(tmp_path)
    (data / "follow" / "team").mkdir(parents=True)
    (data / "follow" / "team" / "OLD.json").write_text("{}", encoding="utf-8")
    B.build(data, NOW)
    assert not (data / "follow" / "team" / "OLD.json").exists()


def test_rating_move_from_the_weekly_history(tmp_path):
    """<S>/rating_history.json (rating_history.py): the weekly ranks feed the "rating move" fact, against today's
    published rank; a week dated after the build clock is never read."""
    data = tree(tmp_path)
    weeks = [(NOW - timedelta(days=d)).date().isoformat() for d in (40, 33, 26, 19, 12, 5)] + [(NOW + timedelta(days=2)).date().isoformat()]
    ranks = {t: [6 if t == "FFF" else 1 if t == "AAA" else 3] * 6 + [1] for t in TEAMS}
    write(data / str(S) / "rating_history.json", {"ok": True, "season": S, "weeks": weeks, "ranks": ranks, "teams": {}})
    B.build(data, NOW)
    cs = cards(data)
    mv = [f["text"] for f in cs["FFF"]["facts"] if f["kind"] == "rating_move"]
    # FFF: 6th a month ago, 2nd on today's published rating (units.rating 0.25, behind AAA's 0.6)
    assert mv == ["The Kraken are up 4 places in our ratings this month, to 2nd."]
    assert not [f for f in cs["AAA"]["facts"] if f["kind"] == "rating_move"]
    # without the file: no rating move anywhere
    (data / str(S) / "rating_history.json").unlink()
    B.build(data, NOW)
    assert not [f for c in cards(data).values() for f in c["facts"] if f["kind"] == "rating_move"]


def test_rating_history_fits_each_monday_on_the_games_before_it(monkeypatch):
    """rating_history.build refits the team ratings at every Monday after the first game day, through today, passing
    the Monday as the fit's exclusive `through` (no game on or after it), and ranks the clubs at each."""
    from datetime import date

    import pandas as pd

    from oddsmarkets.nhl.analytics import rating_history as RH
    from oddsmarkets.nhl.models import _cdata as D
    from oddsmarkets.nhl.models import team_strength as TS
    assert RH.mondays(date(2026, 10, 7), date(2026, 10, 26)) == [date(2026, 10, 12), date(2026, 10, 19), date(2026, 10, 26)]
    assert RH.mondays(date(2026, 10, 5), date(2026, 10, 11)) == []           # a Monday start: its own day is not a point
    seen = []

    class R:
        def __init__(self, through):
            self.through = through

        def as_dict(self):
            k = len(seen)
            return {"teams": {"AAA": {"net": 0.15 * k}, "BBB": {"net": 0.2}, "CCC": {"net": -0.1}}}

    def fit(tg, season, through, prior, p, teams=None, goalie_ext=None):
        seen.append((through, goalie_ext))
        return R(through)
    monkeypatch.setattr(D, "team_games", lambda s: pd.DataFrame({"date": ["2026-10-07", "2026-10-20"], "season": [s, s]}))
    monkeypatch.setattr(D, "teams_for", lambda s: ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(TS, "fit", fit)
    out = RH.build(S, date(2026, 10, 26), rd={"prior": {"teams": {}, "goalies": {}}})
    assert out["ok"] and out["weeks"] == ["2026-10-12", "2026-10-19", "2026-10-26"]
    assert [x[0] for x in seen] == out["weeks"] and all(x[1] is None for x in seen)
    assert out["ranks"]["BBB"] == [1, 2, 2] and out["ranks"]["AAA"] == [2, 1, 1] and out["ranks"]["CCC"] == [3, 3, 3]
