"""A tiny, deterministic payload tree in the shapes of oddsmarkets/college/PAYLOADS.md, for the site tests.

`make(root)` writes data/<L>/... for cfb (seasons 2025, 2026) and mbb (2027 only, preseason); wbb is left out so
the tests can check how a missing level is reported. No network, no stores.
"""
from __future__ import annotations

import json
from pathlib import Path


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


TEAMS_CFB = {
    "1": {"name": "Alpha State Owls", "short": "Alpha St", "abbr": "ALP", "colour": "#112233", "alt_colour": None, "conference": "8", "member": True},
    "2": {"name": "Beta Tech Bees", "short": "Beta Tech", "abbr": "BET", "colour": "#aa2200", "alt_colour": None, "conference": "8", "member": True},
    "3": {"name": "Gamma University", "short": "Gamma", "abbr": "GAM", "colour": None, "alt_colour": None, "conference": "5", "member": True},
    "9": {"name": "Delta FCS College", "short": "Delta", "abbr": "DEL", "colour": None, "alt_colour": None, "conference": None, "member": False},
}


def card(gid, date, status, home, away, hs=None, as_=None, p=0.6, mk=None, hr=None, ar=None, season=2026, stype="reg"):
    return {"id": gid, "season": season, "date": date, "status": status, "stype": stype, "round": None, "region": None, "note": None,
            "week": 8, "home": home, "away": away, "hs": hs, "as": as_, "hr": hr, "ar": ar, "hseed": None, "aseed": None,
            "neutral": False, "conf_game": True, "period": None, "clock": None, "model": {"p_home": p, "margin": 3.0, "total": 50.0},
            "market": None if mk is None else {"p_home": mk, "spread_home": -3.0, "total": 51.0, "source": "espn"}, "result": None}


def make(root: Path) -> Path:
    data = Path(root)
    # ── cfb 2026 (current) ──
    S = data / "cfb" / "2026"
    games = [
        card("101", "2026-10-17T19:30:00Z", "post", "1", "2", 31, 24, 0.7),
        card("102", "2026-10-18T23:00:00Z", "post", "3", "9", 45, 10, 0.95),
        card("103", "2026-10-19T23:00:00Z", "in", "2", "3", 7, 3, 0.55),
        card("104", "2026-10-20T23:00:00Z", "pre", "1", "3", p=0.52, mk=0.45, hr=5),
        card("105", "2026-10-21T23:00:00Z", "pre", "2", "1", p=0.9),
        card("106", "2026-11-20T23:00:00Z", "pre", "3", "2", p=0.5),
    ]
    _w(S / "schedule.json", {"ok": True, "level": "cfb", "season": 2026, "games": games})
    _w(S / "season.json", {
        "ok": True, "level": "cfb", "season": 2026, "phase": "regular", "week": 8, "format": {},
        "conferences": {"8": {"name": "Southeastern Conference", "short": "SEC", "teams": ["1", "2"]}, "5": {"name": "Big Ten Conference", "short": "Big Ten", "teams": ["3"]}},
        "teams": TEAMS_CFB,
        "standings": {"8": [{"team": "1", "w": 6, "l": 1}, {"team": "2", "w": 4, "l": 3}], "5": [{"team": "3", "w": 7, "l": 0}]},
        "ratings": {"1": {"rating": 12.5, "se": 3.0}, "2": {"rating": 2.0, "se": 3.1}, "3": {"rating": 18.0, "se": 2.9}},
        "polls": {"ap": [{"rank": 1, "team": "3", "points": 1500, "first": 50, "prev": 2}, {"rank": 5, "team": "1", "points": 900, "first": 0, "prev": 4}]},
        "power": [{"rank": 1, "team": "3", "rating": 18.0, "prev_rank": 1}, {"rank": 2, "team": "1", "rating": 12.5, "prev_rank": 2}, {"rank": 3, "team": "2", "rating": 2.0, "prev_rank": 3}],
        "sim": {"n_sims": 100, "teams": {"1": {"p_title": 0.1}, "2": {"p_title": 0.0}, "3": {"p_title": 0.3}}}, "leaders": {}})
    _w(S / "players.json", {"ok": True, "metrics": [{"key": "epa", "label": "EPA", "group": "Value", "fmt": "1", "lower": False, "desc": "Expected points added in total"}],
                            "positions": {"QB": {"label": "Quarterbacks", "n": 2}}, "min_floor": {},
                            "players": {"p1": {"name": "Ann Arbor", "team": "1", "pos": "QB", "gp": 7, "qualified": True, "values": {"epa": 40.0}, "pct": {}, "pct_pos": {}},
                                        "p2": {"name": "Bo Nocareer", "team": "2", "pos": "QB", "gp": 7, "qualified": True, "values": {"epa": 10.0}, "pct": {}, "pct_pos": {}}}})
    _w(S / "teams.json", {"ok": True, "metrics": [{"key": "rating", "label": "Rating", "group": "Overall", "fmt": "signed1", "lower": False, "desc": "Points v average"}], "teams": {}})
    _w(data / "cfb" / "players" / "p1.json", {"ok": True, "id": "p1", "name": "Ann Arbor", "pos": "QB", "seasons": [], "current": {"season": 2026, "team": "1"}})
    _w(data / "cfb" / "players" / "p3.json", {"ok": True, "id": "p3", "name": "Cy Oldtimer", "pos": "RB", "seasons": [], "current": {"season": 2025, "team": "3"}})
    _w(data / "cfb" / "markets.json", {"ok": True, "level": "cfb", "season": 2026, "futures": {"champion": {"probs": {"3": 0.35, "1": 0.08}}}})
    _w(data / "cfb" / "history.json", {"ok": True, "level": "cfb", "champions": [{"season": 2025, "team": "3"}]})
    # ── cfb 2025 (past) ──
    _w(data / "cfb" / "2025" / "season.json", {"ok": True, "level": "cfb", "season": 2025, "phase": "offseason", "teams": TEAMS_CFB})
    # a broken season folder (no season.json) is ignored
    (data / "cfb" / "2019").mkdir(parents=True, exist_ok=True)
    # ── mbb 2027 (preseason) ──
    M = data / "mbb" / "2027"
    _w(M / "season.json", {"ok": True, "level": "mbb", "season": 2027, "phase": "preseason", "week": None,
                           "teams": {"20": {"name": "Hoop U", "short": "Hoop", "abbr": "HOOP", "colour": "#003366", "conference": "7", "member": True},
                                     "21": {"name": "Rim State", "short": "Rim St", "abbr": "RIM", "colour": "#660000", "conference": "7", "member": True}},
                           "conferences": {"7": {"name": "Big Ten Conference", "short": "Big Ten", "teams": ["20", "21"]}},
                           "power": [{"rank": 1, "team": "20", "rating": 20.0}], "sim": {"teams": {"20": {"p_title": 0.2}}}})
    _w(M / "schedule.json", {"ok": True, "games": [card("901", "2026-11-03T00:00:00Z", "pre", "20", "21", p=0.8, season=2027),
                                                   card("902", "2026-11-25T00:00:00Z", "pre", "21", "20", p=0.3, season=2027)]})
    return data
