"""
The Campus standings pages: top and bottom performers (data/<L>/<S>/performers.json) for each level and season, from
that season's players.json and season.json (oddsmarkets/common/performers.py writes the shape; the kit's
QKL.leaders draws it).

    build(level, players, season_doc, season) -> the document, or None
    write(level, data_dir, season) -> summary (reads the two payloads the level's builder has just written)

Views:
- football (FBS): All players on our value model (value per game and in total); QB, RB, WR, TE, DL, LB, DB, K, P on
  their spec headline sets (docs/_design/metrics/college.json cfb_*), qualified on the spec's field
  (`qualified_rate`: e.g. 12.5 dropbacks a team game for quarterbacks); the FBS teams on cfb_teams (our rating,
  offence and defence, opponent-adjusted EPA and success rates) from season.json `ratings`.
- basketball (Division I): All players (box rating and value, ours, then points, rebounds and assists a game);
  Guards, Forwards and Centers (the payload's positions) on what players.json carries for each: the spec's headline
  sets per 100 possessions (pts100, ts_add, ...) are not in the payload, so the per-game box score stands in; the
  teams on our rating, offence and defence (per 100 possessions). `qualified`: the spec's games and minutes floor.
Season to date only: no look-ahead.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from oddsmarkets.common import performers as P

FMT = {"value": "+1", "value_pg": "+2", "epa_play": "+3", "sr_db": "pct1", "cmp_pct": "pct1", "ypa": "1", "td_rate": "pct1",
       "int_rate": "pct1", "rush_pg": "1", "sr_rush": "pct1", "ypc": "1", "rush_share": "pct1", "tgt_share": "pct1",
       "yptpa": "2", "ypr": "1", "sr_tgt": "pct1", "havoc_pg": "2", "sacks_pg": "2", "hurries_pg": "2", "tkl_pg": "1",
       "pd_pg": "2", "tfl_pg": "2", "def_int_pg": "2", "fg_pct": "pct1", "xp_pct": "pct1", "gross": "1", "in20_rate": "pct1",
       "tb_rate": "pct1", "rating": "+1", "off": "+1", "def": "+1", "epa_off": "+3", "epa_def": "+3", "sr_off": "pct1",
       "sr_def": "pct1", "r": "+1", "pts": "1", "reb": "1", "ast": "1", "stl": "1", "blk": "1", "tov": "1", "ts": "pct1"}
CFB_POS = [("QB", "qb", "QB", "quarterbacks", "12.5 dropbacks a team game"), ("RB", "rb", "RB", "running backs", "6.25 carries a team game"),
           ("WR", "wr", "WR", "wide receivers", "2.5 targets a team game"), ("TE", "te", "TE", "tight ends", "1.67 targets a team game"),
           ("DL", "dl", "DL", "defensive linemen", "60% of the team's games"), ("LB", "lb", "LB", "linebackers", "60% of the team's games"),
           ("DB", "db", "DB", "defensive backs", "60% of the team's games"), ("K", "k", "K", "kickers", "0.67 field-goal attempts a team game"),
           ("P", "p", "P", "punters", "1.67 punts a team game")]
VALUE_NAME = "Campus value model"
BOX_NAME = "Box rating"


def _m(key, label, unit, tip, ours=None, d="higher"):
    m = {"key": key, "label": label, "unit": unit, "dir": d, "fmt": FMT.get(key), "tip": tip}
    if ours:
        m["ours"] = ours
    return m


HOOPS_BOX = {
    "pts": _m("pts", "Points", "a game", "Points per game."),
    "reb": _m("reb", "Rebounds", "a game", "Rebounds per game."),
    "ast": _m("ast", "Assists", "a game", "Assists per game."),
    "stl": _m("stl", "Steals", "a game", "Steals per game."),
    "blk": _m("blk", "Blocks", "a game", "Blocks per game."),
    "tov": _m("tov", "Turnovers", "a game", "Turnovers per game: fewer is better.", d="lower"),
    "ts": _m("ts", "True shooting", "", "Points per shot, counting threes and free throws: points / (2 x (FGA + 0.44 x FTA))."),
}
HOOPS_POS = [("G", "guards", "Guards", ["pts", "ast", "ts", "stl", "tov"]), ("F", "forwards", "Forwards", ["pts", "reb", "ts", "stl", "blk"]),
             ("C", "centers", "Centers", ["pts", "reb", "blk", "ts", "tov"])]


def _players(cat: dict | None) -> dict:
    from oddsmarkets.college import packing as PK
    Pl = (cat or {}).get("players")
    if PK.is_packed(Pl):
        Pl = PK.unpack(Pl)
    if isinstance(Pl, list):
        Pl = {str(r.get("id")): r for r in Pl if isinstance(r, dict)}
    return Pl if isinstance(Pl, dict) else {}


def _clean_tip(m: dict) -> dict:
    m["tip"] = re.sub(r"\s*\([^)]*\.json[^)]*\)", "", m.get("tip") or "")
    return m


def _team_view(level: str, spec: dict, season_doc: dict | None, keys: list[str] | None = None) -> dict | None:
    sd = season_doc or {}
    R, T = sd.get("ratings") or {}, sd.get("teams") or {}
    rows = [{"id": str(tid), "name": (T.get(str(tid)) or {}).get("name") or str(tid), "team": str(tid), "v": r}
            for tid, r in R.items() if isinstance(r, dict) and (T.get(str(tid)) or {}).get("member", True)]
    ms = [_clean_tip(m) for m in P.spec_metrics(spec, f"{level}_teams", fmt=FMT, only=set(keys) if keys else None)]
    if level != "cfb":
        for m in ms:
            if m["key"] in ("off", "def"):
                m["fmt"] = "1"
    return P.view("teams", "Teams", rows, ms, entity="team", peer="FBS teams" if level == "cfb" else "Division I teams")


def build(level: str, players: dict | None, season_doc: dict | None, season) -> dict | None:
    spec = P.load_spec("college")
    Pl = _players(players) if (players or {}).get("ok", True) else {}
    fb = level == "cfb"
    qfield = "qualified_rate" if fb else "qualified"
    by_pos: dict[str, list] = {}
    for pid, p in Pl.items():
        if not isinstance(p, dict) or not p.get(qfield, p.get("qualified")) or not p.get("pos"):
            continue
        by_pos.setdefault(p["pos"], []).append({"id": str(pid), "name": p.get("name") or "", "team": str(p.get("team") or ""), "v": p.get("values") or {}})
    every = [r for rows in by_pos.values() for r in rows]
    about = (spec.get("our_models") or {}).get("models") or {}
    vtip = (about.get("value") or {}).get("about", "")
    views = []
    if fb:
        views.append(P.view("all", "All players", every, [_m("value_pg", "Value per game", "points a game", vtip, VALUE_NAME),
                                                          _m("value", "Value", "points, season to date", vtip, VALUE_NAME)],
                            peer="FBS players", min_text="the minimums at each position"))
        for pos, gid, label, peer, mn in CFB_POS:
            ms = [_clean_tip(m) for m in P.spec_metrics(spec, f"cfb_{gid}", fmt=FMT)]
            views.append(P.view(pos.lower(), label, by_pos.get(pos, []), ms, peer=peer, min_text=mn))
        views.append(_team_view("cfb", spec, season_doc))
    else:
        btip = (about.get("box") or {}).get("about", "")
        head = [_m("r", "Box rating", "points per 100 possessions", btip, BOX_NAME), _m("value_pg", "Value per game", "points a game", vtip, VALUE_NAME)]
        views.append(P.view("all", "All players", every, head + [_m("value", "Value", "points, season to date", vtip, VALUE_NAME)] +
                            [HOOPS_BOX[k] for k in ("pts", "reb", "ast")], peer="Division I players",
                            min_text="40% of the season's most games and 10 minutes a game"))
        for pos, key, label, box in HOOPS_POS:
            views.append(P.view(key, label, by_pos.get(pos, []), head + [HOOPS_BOX[k] for k in box], peer=label.lower(),
                                min_text="40% of the season's most games and 10 minutes a game"))
        views.append(_team_view(level, spec, season_doc, ["rating", "off", "def"]))
    doc = P.document(views, season=int(season) if str(season).isdigit() else season, level=level,
                     updated_at=(players or {}).get("updated_at") or (season_doc or {}).get("updated_at"))
    return doc if doc["views"] else None


def write(level: str, data_dir: Path, season) -> dict:
    folder = Path(data_dir) / level / str(season)

    def rd(name):
        f = folder / name
        if not f.exists():
            return None
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            return None
        return d if isinstance(d, dict) and d.get("ok") is not False else None

    doc = build(level, rd("players.json"), rd("season.json"), season)
    if not doc:
        return {"ok": False, "reason": "nothing qualified"}
    return {"ok": True, "bytes": P.write(folder / "performers.json", doc), "views": len(doc["views"])}
