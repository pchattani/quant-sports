"""
The Gridiron's standings page: top and bottom performers (data/<S>/performers.json), from that season's players.json
(the metric catalogue) and value.json (Gridiron Value and the value position). oddsmarkets/common/performers.py
writes the shape; the kit's QKL.leaders draws it.

    build(players, value, season) -> the document, or None when nobody qualifies

Views:
- All players: Gridiron Value per game and in total (our model), every qualified player with a value (value.json `q`,
  the pool the team pages rank against);
- QB, RB, WR, TE, EDGE, DL, LB, CB, S, K, P: each spec group's headline set (docs/_design/metrics/nfl.json), qualified
  players only (players.json `qualified`: the spec's minimums, e.g. 14 attempts a team game for quarterbacks). The
  position is value.json's (EDGE / DL split by role); players.json's group where value.json has none. Style metrics
  (aDOT, time to throw, scramble rate, kick distance) get no board. Defensive counts are per game (tackles, TFL, passes
  defensed, interceptions, forced fumbles over games played).
The teams view comes from season.json's league block in the page. Season to date only: no look-ahead.
"""
from __future__ import annotations

import re

from oddsmarkets.common import performers as P

FMT = {"gvar": "+1", "gvar_pg": "+2", "composite": "1", "epa_db": "+3", "cpoe": "+1", "sack_rate": "pct1", "int_rate": "pct1",
       "pressure_rate": "pct1", "ryoe": "+2", "rush_success": "pct1", "explosive": "pct1", "rush_epa": "+3", "stuff_rate": "pct1",
       "target_share": "pct1", "yptpa": "2", "rec_epa_tgt": "+3", "croe": "+1", "yac_rec": "1", "pressures_pg": "2",
       "tfl_pg": "2", "tackles_pg": "1", "ff_pg": "2", "pd_pg": "2", "ints_pg": "2", "splash_pg": "2", "fg_oe": "+2",
       "fg_50_pct": "pct0", "xp_pct": "pct1", "fg_50": "0", "epa_punt": "+3", "net": "1", "gross": "1", "inside20": "pct1",
       "touchback_rate": "pct1"}
# value position -> (spec group, label, peer noun)
GROUPS = [("QB", "qb", "QB", "quarterbacks"), ("RB", "rb", "RB", "running backs"), ("WR", "wr", "WR", "wide receivers"),
          ("TE", "te", "TE", "tight ends"), ("EDGE", "edge", "Pass rushers", "outside pass rushers"), ("DL", "idl", "Interior DL", "interior linemen"),
          ("LB", "lb", "LB", "linebackers"), ("CB", "cb", "CB", "cornerbacks"), ("S", "s", "S", "safeties"),
          ("K", "k", "K", "kickers"), ("P", "p", "P", "punters")]
MIN_TEXT = {"QB": "14 pass attempts a team game", "RB": "6.25 carries a team game", "WR": "3 targets a team game",
            "TE": "2 targets a team game", "K": "0.8 field-goal attempts a team game", "P": "2 punts a team game"}
DEF_MIN = "half the team's games and 2.5 tackles-equivalent a team game"
PER_GAME = {"tackles_pg": "tackles", "tfl_pg": "tfl", "pd_pg": "pd", "ints_pg": "ints", "ff_pg": "ff"}
# CPOE is stored in percentage points; the spec's unit says so, the board shows "+2.4"
UNIT = {"cpoe": "points", "croe": "points"}


def _value_rows(value: dict | None) -> dict[str, dict]:
    if not (value or {}).get("ok") or not isinstance(value.get("rows"), list) or not isinstance(value.get("cols"), list):
        return {}
    ix = {c: i for i, c in enumerate(value["cols"])}
    out = {}
    for r in value["rows"]:
        g = (lambda k: r[ix[k]] if k in ix and ix[k] < len(r) else None)
        out[str(g("pid"))] = {"name": g("name"), "team": g("team"), "pos": g("pos"), "gvar": g("gvar"), "gvar_pg": g("gvar_pg"), "q": g("q")}
    return out


def build(players: dict | None, value: dict | None, season) -> dict | None:
    spec = P.load_spec("nfl")
    V = _value_rows(value)
    cat = (players or {}).get("players") if (players or {}).get("ok") else {}
    cat = cat if isinstance(cat, dict) else {}
    # all players on Gridiron Value: value.json's own qualified pool
    all_rows = [{"id": pid, "name": x.get("name") or "", "team": x.get("team") or "", "v": {"gvar": x.get("gvar"), "gvar_pg": x.get("gvar_pg")}}
                for pid, x in V.items() if x.get("q")]
    gv_tip = (spec.get("our_models") or {}).get("models", {}).get("value", {}).get("about", "")
    ALL = [{"key": "gvar_pg", "label": "Gridiron Value per game", "unit": "points a game", "ours": "Gridiron Value (GVAR)", "fmt": "+2", "tip": gv_tip},
           {"key": "gvar", "label": "Gridiron Value", "unit": "points, season to date", "ours": "Gridiron Value (GVAR)", "fmt": "+1", "tip": gv_tip}]
    views = [P.view("all", "All players", all_rows, ALL, peer="players", min_text="the minimums at each position")]
    by_pos: dict[str, list] = {}
    for pid, p in cat.items():
        if not isinstance(p, dict) or not p.get("qualified"):
            continue
        vx = V.get(str(pid)) or {}
        pos = vx.get("pos") or p.get("group")
        vals = dict(p.get("values") or {})
        g = p.get("games") or 0
        for k, src in PER_GAME.items():
            if k not in vals and g and P.num(vals.get(src)) is not None:
                vals[k] = P.num(vals[src]) / g
        if P.num(vx.get("gvar_pg")) is not None:
            vals["gvar_pg"] = vx["gvar_pg"]
        by_pos.setdefault(pos, []).append({"id": str(pid), "name": p.get("name") or vx.get("name") or "", "team": p.get("team") or vx.get("team") or "", "v": vals})
    for pos, gid, label, peer in GROUPS:
        ms = P.spec_metrics(spec, gid, fmt=FMT)
        for m in ms:
            # the spec's explanations name payload files in brackets: not for the page
            m["tip"] = re.sub(r"\s*\([^)]*\.json[^)]*\)", "", m.get("tip") or "")
            if m["key"] in UNIT:
                m["unit"] = UNIT[m["key"]]
        views.append(P.view(pos.lower(), label, by_pos.get(pos, []), ms, peer=peer, min_text=MIN_TEXT.get(pos, DEF_MIN)))
    doc = P.document(views, season=int(season) if str(season).isdigit() else season,
                     team_games=(players or {}).get("team_games") or (value or {}).get("team_games"),
                     updated_at=(players or {}).get("updated_at") or (value or {}).get("updated_at"))
    return doc if doc["views"] else None
