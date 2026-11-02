"""oddsmarkets/f1/analytics/follow_build.py: the Paddock's follow cards from a synthetic payload tree."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL
from oddsmarkets.f1.analytics import follow_build as B

NOW = datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc)
DRV = {"ant": ("Andrea Kimi Antonelli", "ANT", "merc"), "rus": ("George Russell", "RUS", "merc"), "ver": ("Max Verstappen", "VER", "rbr"),
       "had": ("Isack Hadjar", "HAD", "rbr"), "lec": ("Charles Leclerc", "LEC", "fer"), "ham": ("Lewis Hamilton", "HAM", "fer")}
TEAMS = {"merc": ("Mercedes", "#00D7B6"), "rbr": ("Red Bull", "#4781D7"), "fer": ("Ferrari", "#ED1131")}
ORDER = ["ant", "ver", "rus", "lec", "ham", "had"]           # the finishing order of every finished round


def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def tree(tmp: Path, clinched: bool = False) -> Path:
    data = tmp / "data"
    pts = [25, 18, 15, 12, 10, 8]
    cal = []
    for r in range(1, 7):
        day = NOW - timedelta(days=7 * (6 - r) + 6) if r <= 5 else NOW + timedelta(days=1)
        cal.append({"round": r, "name": f"Race {r} Grand Prix", "date": day.date().isoformat(), "time": "14:00:00Z", "status": "done" if r <= 5 else "upcoming"})
        res = [{"pos": i + 1, "driver": d, "team": DRV[d][2], "points": float(pts[i]), "classified": True, "grid": i + 1} for i, d in enumerate(ORDER)] if r <= 5 else []
        fc = {"pre_quali": {"generated_at": (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "drivers": {d: {"p_win": 0.4 if d == "ant" else 0.12, "p_podium": 0.8 if d == "ant" else 0.4} for d in DRV},
                            "teams": {t: {"exp_points": 20.0} for t in TEAMS}}}
        if r == 6:
            # a post-qualifying forecast stamped after the clock: never read
            fc["post_quali"] = {"generated_at": (NOW + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"), "drivers": {d: {"p_win": 0.99} for d in DRV}}
        write(data / "2026" / "races" / f"{r}.json", {"ok": True, "round": r, "results": res, "forecast": fc})
    tot = {d: 5 * pts[i] for i, d in enumerate(ORDER)}
    standings = {"drivers": [{"pos": i + 1, "driver": d, "team": DRV[d][2], "points": float(tot[d]), "wins": 5 if d == "ant" else 0} for i, d in enumerate(ORDER)],
                 "constructors": [{"pos": i + 1, "team": t, "points": float(sum(tot[d] for d in DRV if DRV[d][2] == t)), "wins": 5 if t == "merc" else 0}
                                  for i, t in enumerate(["merc", "rbr", "fer"])]}
    champ = {"n_sims": 20000, "max_points_left": {"driver": 26, "team": 44},
             "drivers": {d: {"p_title": 1.0 if d == "ant" else 0.0, "magic": 9.0 if d == "ant" else 200.0, "clinched": clinched and d == "ant",
                             "eliminated": d != "ant"} for d in DRV},
             "constructors": {t: {"p_title": 0.97 if t == "merc" else 0.03 if t == "rbr" else 0.0, "clinched": False, "eliminated": t == "fer"} for t in TEAMS}}
    week_ago = (NOW - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%SZ")
    th = [{"as_of": week_ago, "drivers": {"ant": {"p_title": 0.8}}, "constructors": {"merc": {"p_title": 0.97}}},
          {"as_of": (NOW + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), "drivers": {"ant": {"p_title": 0.1}}}]
    write(data / "2026" / "season.json", {"ok": True, "year": 2026, "updated_at": (NOW - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"), "rounds_total": 6,
                                          "rounds_done": 5, "finished": False, "calendar": cal, "standings": standings, "championship": champ, "title_history": th,
                                          "elo": {d: {"elo": 1700.0 - 10 * i} for i, d in enumerate(ORDER)},
                                          "names": {d: v[0] for d, v in DRV.items()}})
    write(data / "2025" / "season.json", {"ok": True, "progression": {"drivers": {"ant": [5, 10, 20, 30, 40, 50]}, "constructors": {"merc": [10, 20, 30, 40, 60]}}})
    vals = {d: {"driver_effect": -0.1 + 0.02 * i, "quali_driver_effect": -0.05 + 0.01 * i, "race_pace": -1.5 + 0.1 * i, "race_h2h": 0.8 - 0.1 * i,
                "quali_h2h": 0.5, "team_points_share": 0.6, "points_per_race": 25 - 3 * i, "lap1_gain": 0.5} for i, d in enumerate(ORDER)}
    pct = {d: {k: max(0, 100 - 18 * i) for k in vals[d]} for i, d in enumerate(ORDER)}
    write(data / "2026" / "drivers.json", {"ok": True, "metrics": [{"key": "driver_effect", "lower": True}, {"key": "quali_driver_effect", "lower": True},
                                                                   {"key": "race_pace", "lower": True}, {"key": "points_per_race"}, {"key": "lap1_gain"}],
                                           "drivers": {d: {"qualified": True, "values": vals[d], "pct": pct[d]} for d in DRV}})
    write(data / "2026" / "teams.json", {"ok": True, "metrics": [{"key": "car_race_pace", "lower": True}],
                                         "teams": {t: {"values": {"car_race_pace": -1.0 + 0.5 * i}, "pct": {"car_race_pace": 100 - 40 * i}} for i, t in enumerate(TEAMS)}})
    write(data / "index.json", {"current_season": 2026, "drivers": {d: {"name": v[0], "code": v[1], "team": v[2]} for d, v in DRV.items()},
                                "teams": {t: {"name": v[0], "colour": v[1], "alt": "#000000"} for t, v in TEAMS.items()}, "seasons_meta": {"2026": {}}})
    return data


def read(data: Path, scope: str, i: str) -> dict:
    return json.loads((data / "follow" / scope / f"{i}.json").read_text(encoding="utf-8"))


def test_every_driver_and_constructor_gets_a_small_card(tmp_path):
    data = tree(tmp_path)
    out = B.build(data, NOW)
    assert out["driver"]["ids"] == sorted(DRV) and out["team"]["ids"] == sorted(TEAMS)
    for scope, ids in (("driver", DRV), ("team", TEAMS)):
        for i in ids:
            c = read(data, scope, i)
            assert c["k"] == f"paddock:{scope}:{i}" and c["team"]["href"] == f"#/{scope}/{i}" and FL.card_bytes(c) <= FL.MAX_BYTES
            assert 3 <= len(c["facts"]) <= 5 and set(f["kind"] for f in c["facts"]) <= set(FL.KINDS) | {"teammate"}
    a = read(data, "driver", "ant")
    assert a["team"]["colour"] == "#00D7B6" and a["team"]["abbr"] == "ANT" and a["now"]["record"] == "125 pts"
    assert a["now"]["standing"]["text"] == "1st in the championship" and a["profile"]["strong"]
    m = read(data, "team", "merc")
    assert [p["href"] for p in m["players"]] == ["#/driver/ant", "#/driver/rus"] and m["now"]["rating"]["label"] == "Car pace"


def test_title_wording_is_literal(tmp_path):
    data = tree(tmp_path)
    B.build(data, NOW)
    a = read(data, "driver", "ant")
    texts = " ".join(f["text"] for f in a["facts"])
    assert "in all 20,000 of our simulated seasons, but has not clinched it: it is not yet mathematically decided" in texts
    assert "champion" not in texts.replace("championship", "") and "champion" not in a
    t = [c for c in a["chances"] if c["key"] == "p_title"][0]
    assert a["chances"][-1]["key"] == "p_title" and t["p"] == 0.9999
    # clinched (the magic number reached): now it may say so
    data2 = tree(tmp_path / "b", clinched=True)
    B.build(data2, NOW)
    assert "has clinched the 2026 drivers’ title with 1 race left." in " ".join(f["text"] for f in read(data2, "driver", "ant")["facts"])


def test_no_look_ahead(tmp_path):
    data = tree(tmp_path)
    B.build(data, NOW)
    a = read(data, "driver", "ant")
    # the post-qualifying forecast stamped after the clock is not read: the pre-qualifying 40% is
    w = [c for c in a["chances"] if c["key"] == "p_win"][0]
    assert w["p"] == 0.4 and "Race 6 GP win" == w["label"]
    assert a["next_note"].startswith("Next: the Race 6 Grand Prix") and "40%" in a["next_note"]
    # the 7-day title change: 1.0 now against 0.8 nine days ago, never the later 0.1
    t = [c for c in a["chances"] if c["key"] == "p_title"][0]
    assert t["d7"] == 0.2      # the change reads the simulation, not the capped display
    # streaks from the finished rounds only
    assert "Antonelli has won the last 5 Grands Prix." in [f["text"] for f in a["facts"]]
    r = {f["kind"]: f["text"] for f in read(data, "driver", "rus")["facts"]}
    assert r.get("teammate") == "Ahead of team-mate Antonelli at the finish in 0 of their 5 races together."
