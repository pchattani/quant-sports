"""
injuries.json (round 9, 28 Oct 2026): who is on each team's injury list now and the value it costs, for the Teams page's
injury impact board. Built from data the build already has, no new fetch:

- the latest snapshot of each team's ESPN injury list (`injury_log.json.gz`, hourly since 22 Oct 2026, store.py);
- the ESPN-to-gsis crosswalk (people.espn_xwalk, the nflverse players release);
- this season's Gridiron Value per game (value.json: points above a replacement player at the position, per game).

Each listed player's chance of missing the next game uses the game model's availability weights (models/availability.py,
the starters-out term): Out, injured reserve, PUP, suspended 1; Doubtful 0.85; Questionable 0.15. A team's "value on the
sidelines" is the sum over its list of max(value per game, 0) x that chance, in points a game: what the absences take
from the lineup in our value model's currency (about 40 points is one win over a season). A player with no value row
(no snaps this season, offensive linemen, who are not valued individually) counts 0 and is listed as unvalued.
"""
from __future__ import annotations

from typing import Any

from oddsmarkets.nfl import analytics as an

P_MISS = {"out": 1.0, "injured reserve": 1.0, "ir": 1.0, "physically unable to perform": 1.0, "pup": 1.0, "suspension": 1.0, "suspended": 1.0,
          "doubtful": 0.85, "questionable": 0.15}
COLS = ["pid", "name", "pos", "status", "injury", "return", "gvar_pg", "p_miss"]


def p_miss(status: str | None) -> float:
    return P_MISS.get(str(status or "").strip().lower(), 0.0)


def build(season: int, log: dict, value: dict | None, xwalk: dict[str, str], names: dict[str, Any]) -> dict | None:
    teams = (log or {}).get("teams") or {}
    if not teams:
        return None
    vrows: dict[str, dict] = {}
    if value and value.get("cols"):
        cols = value["cols"]
        for r in value.get("rows") or []:
            o = dict(zip(cols, r))
            if o.get("pid"):
                vrows[str(o["pid"])] = o
    out: dict[str, dict] = {}
    as_of = None
    for team, snaps in teams.items():
        if not snaps:
            continue
        at, rows = snaps[-1][0], snaps[-1][1]
        as_of = max(as_of or at, at)
        players = []
        for r in rows:
            espn, status = str(r[0]), r[1]
            pm = p_miss(status)
            if pm <= 0:
                continue
            pid = xwalk.get(espn)
            v = vrows.get(pid or "")
            nm = (v or {}).get("name") or ((names.get(pid) or {}).get("name") if pid else None)
            gpg = an.fnum((v or {}).get("gvar_pg"))
            players.append([pid, nm, r[6] if len(r) > 6 else None, status, r[3] if len(r) > 3 else None, r[5] if len(r) > 5 else None,
                            an.rnd(gpg, 2) if gpg is not None else None, pm])
        players.sort(key=lambda x: -((max(x[6] or 0.0, 0.0)) * x[7]))
        out[team] = {"at": at, "out_pg": an.rnd(sum(max(x[6] or 0.0, 0.0) * x[7] for x in players), 2),
                     "n_out": sum(1 for x in players if x[7] >= 0.85), "n_q": sum(1 for x in players if x[7] < 0.85), "players": players}
    if not out:
        return None
    return {"ok": True, "season": season, "updated_at": an.now(), "as_of": as_of, "cols": COLS, "weights": P_MISS,
            "unit": "Gridiron Value points a game (points above a replacement player at the position)", "teams": out,
            "credits": "Injury lists: ESPN's public NFL injury reports, snapshotted hourly by us; values: our player value model."}
