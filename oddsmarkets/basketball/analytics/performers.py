"""
The Hardwood's standings page: top and bottom performers (data/<L>/<S>/performers.json), from that season's
players.json (oddsmarkets/common/performers.py writes the shape; the kit's QKL.leaders draws it).

    build(catalogue, league, season) -> the document, or None when nobody has qualified

Views: all players (our plus-minus first, then the box-score headlines), then guards, wings and bigs, each on its
spec headline set (docs/_design/metrics/basketball.json, groups <league>_guards / _wings / _bigs). Qualified players
only: players.json `qualified` (minutes at least `min_floor`, a fifth of the season's most played: the spec's floor);
the role is players.json `role` (G, W, B), as on the team pages. The teams view comes from season.json's league
block in the page. Season to date only: no look-ahead.
"""
from __future__ import annotations

from oddsmarkets.common import performers as P

# QKL.fmtVal codes for the boards
FMT = {"hpm": "+1", "hpm_o": "+1", "hpm_d": "+1", "pts100": "1", "ts_add": "+1", "pox100": "+1", "ast_pct": "pct1",
       "ast_tov": "2", "fta100": "1", "stl_pct": "pct1", "drb_pct": "pct1", "orb_pct": "pct1", "blk_pct": "pct1",
       "pts_g": "1", "reb_g": "1", "ast_g": "1", "ts": "pct1"}
ROLES = [("G", "guards", "Guards", "guards"), ("W", "wings", "Wings", "wings"), ("B", "bigs", "Bigs", "bigs")]
OURS = "Impact model (HPM)"
# the league-wide board for every player: our plus-minus and its two halves, then the box-score headlines
ALL = [("hpm", "Total impact (HPM)", "per 100", OURS,
        "Points per 100 possessions a player adds over an average player, offence plus defence: our plus-minus."),
       ("hpm_o", "Offensive impact", "per 100", OURS, "The offensive half of our plus-minus, per 100 possessions."),
       ("hpm_d", "Defensive impact", "per 100", OURS, "The defensive half of our plus-minus, per 100 possessions (higher is better)."),
       ("pts_g", "Points per game", "", None, "Points scored per game played."),
       ("reb_g", "Rebounds per game", "", None, "Offensive plus defensive rebounds per game."),
       ("ast_g", "Assists per game", "", None, "Assists per game."),
       ("ts", "True shooting", "", None, "Points per shooting attempt, counting threes and free throws: the scoring efficiency number.")]


def _players(cat: dict | None) -> dict:
    P_ = (cat or {}).get("players") or {}
    return P_ if isinstance(P_, dict) else {}


def _rows(cat: dict | None, role: str | None) -> list[dict]:
    out = []
    for pid, p in _players(cat).items():
        if not isinstance(p, dict) or not p.get("qualified"):
            continue
        if role is not None and p.get("role") != role:     # a catalogue built before roles: the all-players view only
            continue
        out.append({"id": str(pid), "name": p.get("name") or "", "team": str(p.get("team") or ""), "v": p.get("values") or {}})
    return out


def build(cat: dict | None, league: str, season) -> dict | None:
    if not cat or cat.get("ok") is False:
        return None
    spec = P.load_spec("basketball")
    floor = cat.get("min_floor")
    min_text = (f"{floor} minutes so far (a fifth of the season's most played)" if floor else "a fifth of the season's most minutes")
    all_ms = [{"key": k, "label": lb, "unit": u, "dir": "higher", "fmt": FMT.get(k), "tip": tip, **({"ours": o} if o else {})}
              for k, lb, u, o, tip in ALL]
    views = [P.view("all", "All players", _rows(cat, None), all_ms, peer="players", min_text=min_text)]
    for code, gid, label, peer in ROLES:
        ms = P.spec_metrics(spec, f"{league}_{gid}", fmt=FMT)
        views.append(P.view(gid, label, _rows(cat, code), ms, peer=peer, min_text=min_text))
    doc = P.document(views, league=league, season=int(season) if str(season).isdigit() else season,
                     updated_at=cat.get("updated_at"), min_floor=floor)
    return doc if doc["views"] else None
