"""
The Footballer's competition pages: top and bottom performers (data/<slug>/performers.json), from the competition's
players_live.json (role and GAR/90 already joined by value_fields) and analytics.json (the club profile).

    build(live, analytics=None, teams=None) -> the document (oddsmarkets/common/performers.py's shape; the kit's
                                               QKL.leaders draws it)
    write_all(data_dir) -> {slug: bytes}       every competition folder with a players_live.json

Views: all players (our value model: GAR/90 and GAR, then the match rating), then each spec position group on its
headline set (docs/_design/metrics/football.json: strikers, attacking midfielders and wingers, central and defensive
midfielders, full-backs, centre-backs, goalkeepers), then the clubs on the spec's club set (possession is how a side
plays, not how well, so it gets no board). Qualified players only: the spec's minimum (450 minutes, goalkeepers 900)
and the competition's floor (players_live minutes_floor, 30% of the season's minutes), whichever is higher, with a
formation role (substitute-only players have none). A position group needs MIN_VIEW qualified players for a board;
a cup early in its run often has none, and the page then leaves the section out. Clubs need the spec's 5 matches.
Percent metrics are stored as shares (0-1) for the page's percent format. Season to date only: no look-ahead.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from oddsmarkets.common import performers as P

logger = logging.getLogger(__name__)

MIN_VIEW = 6
CLUB_MIN = 5
GROUPS = [  # (spec group, picker label, peer noun, roles)
    ("st", "Strikers", "strikers", {"ST"}),
    ("am_w", "AM / Wingers", "attacking midfielders and wingers", {"AM", "W"}),
    ("dm_cm", "Midfielders", "central and defensive midfielders", {"DM", "CM"}),
    ("fb", "Full-backs", "full-backs", {"FB"}),
    ("cb", "Centre-backs", "centre-backs", {"CB"}),
    ("gk", "Goalkeepers", "goalkeepers", {"GK"}),
]
FINE = {r for g in GROUPS for r in g[3]}
SPEC_MIN = {"GK": 900}
DEFAULT_MIN = 450
PCT_KEYS = {"aerial_pct", "pass_pct", "long_ball_pct", "save_pct", "field_tilt", "possession", "duel_pct", "dribble_pct",
            "sot_pct", "tackle_pct"}
FMT = {"gar90": "+2", "gar": "+1", "rating": "2", "goals_prevented_90": "+2", "passes_90": "1", "xg_diff": "+2",
       "sot_diff": "+2", "xg_for": "2", "xg_against": "2", "big_chances": "1", "ppda": "1"}
VALUE_MODEL = "Player value model"
ALL = [{"key": "gar90", "label": "Value added (GAR/90)", "unit": "goals per 90", "ours": VALUE_MODEL, "fmt": "+2",
        "tip": "Goals of expected goal difference a player adds per 90 minutes over a replacement-level player in the same role, from our player value model."},
       {"key": "gar", "label": "Value added (GAR)", "unit": "goals", "ours": VALUE_MODEL, "fmt": "+1",
        "tip": "Goals above a replacement-level player in the same role over the season so far: GAR/90 times the minutes played."},
       {"key": "rating", "label": "Match rating", "unit": "rating", "fmt": "2",
        "tip": "Sofascore's 1-10 match rating, averaged over the player's matches and weighted by minutes."}]


def _fmt_for(spec: dict) -> dict:
    out = dict(FMT)
    for g in spec.get("groups") or []:
        for m in g.get("metrics") or []:
            mid = m.get("id")
            if mid and mid not in out:
                out[mid] = "pct1" if mid in PCT_KEYS else "2"
    return out


def _vals(r: dict) -> dict:
    v = {}
    for k, x in r.items():
        f = P.num(x)
        if f is None or isinstance(x, bool):
            continue
        v[k] = f / 100 if k in PCT_KEYS else f
    g90, mins = P.num(r.get("gar90")), P.num(r.get("minutes"))
    if g90 is not None and mins:
        v["gar"] = g90 * mins / 90
    return v


def _qualified(live: dict) -> list[tuple[str, dict]]:
    floor = P.num(live.get("minutes_floor")) or 0
    out = []
    for r in live.get("players") or []:
        role = r.get("role")
        if role not in FINE:
            continue
        mins = P.num(r.get("minutes")) or 0
        if mins < max(SPEC_MIN.get(role, DEFAULT_MIN), floor):
            continue
        tid = r.get("tid")
        out.append((role, {"id": str(r.get("player_id")), "name": r.get("name") or "",
                           "team": str(tid) if tid not in (None, "") else (r.get("team") or ""), "v": _vals(r)}))
    return out


def _clubs(analytics: dict | None, teams: dict | None, spec: dict, fmt: dict) -> dict | None:
    T = (analytics or {}).get("teams") or {}
    ids = {name: (t or {}).get("team_id") for name, t in ((teams or {}).get("teams") or {}).items()}
    rows = []
    for name, t in T.items():
        if not isinstance(t, dict) or (P.num(t.get("played")) or 0) < CLUB_MIN:
            continue
        tid = ids.get(name)
        key = str(tid) if tid not in (None, "") else name
        v = {}
        for k, x in (t.get("profile") or {}).items():
            f = P.num((x or {}).get("v")) if isinstance(x, dict) else None
            if f is not None:
                v[k] = f / 100 if k in PCT_KEYS else f
        rows.append({"id": key, "name": name, "team": key, "v": v})
    if len(rows) < MIN_VIEW:
        return None
    ms = P.spec_metrics(spec, "clubs", fmt=fmt, skip={"possession"})
    return P.view("clubs", "Clubs", rows, ms, entity="team", peer="clubs", min_text=f"{CLUB_MIN} matches")


def build(live: dict | None, analytics: dict | None = None, teams: dict | None = None) -> dict:
    spec = P.load_spec("football")
    fmt = _fmt_for(spec)
    live = live if isinstance(live, dict) and live.get("ok", True) else {}
    q = _qualified(live)
    floor = int(P.num(live.get("minutes_floor")) or 0)
    def mn(base: int) -> str:
        return f"{max(base, floor)} minutes in a formation role" + (f" (the competition's floor is {floor})" if floor > base else "")
    views = []
    allrows = [r for _role, r in q]
    if len(allrows) >= MIN_VIEW:
        views.append(P.view("all", "All players", allrows, ALL, peer="players", min_text=f"{max(DEFAULT_MIN, floor)} minutes in a formation role ({max(900, floor)} for goalkeepers)"))
    for gid, label, peer, roles in GROUPS:
        rows = [r for role, r in q if role in roles]
        if len(rows) < MIN_VIEW:
            continue
        base = SPEC_MIN.get(next(iter(roles)), DEFAULT_MIN)
        views.append(P.view(gid, label, rows, P.spec_metrics(spec, gid, fmt=fmt, ours_names={"value": VALUE_MODEL}),
                            peer=peer, min_text=mn(base)))
    views.append(_clubs(analytics, teams, spec, fmt))
    for v in views:
        for m in (v or {}).get("metrics") or []:
            _signed_round(m)
    return P.document(views, updated_at=live.get("updated_at"), minutes_floor=floor or None)


def _signed_round(m: dict) -> None:
    """A signed format shows exactly its digits: round there (the ranks are already set on the full value), so a
    value just under zero reads 0.00, not -0.00."""
    f = str(m.get("fmt") or "")
    if not f.startswith("+") or not f[1:].isdigit():
        return
    d = int(f[1:])
    for r in (m.get("top") or []) + (m.get("bot") or []):
        x = round(r[3], d)
        r[3] = 0.0 if x == 0 else x


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_all(data_dir: Path | str) -> dict[str, int]:
    """performers.json beside every competition's players_live.json; an empty document when nothing qualifies, so the
    page never requests a missing file."""
    out = {}
    for d in sorted(Path(data_dir).iterdir()):
        live_p = d / "players_live.json"
        if not d.is_dir() or not live_p.exists():
            continue
        try:
            doc = build(_read(live_p), _read(d / "analytics.json"), _read(d / "teams.json"))
            out[d.name] = P.write(d / "performers.json", doc)
        except Exception as exc:  # noqa: BLE001  (one competition never stops the rest)
            logger.error("performers %s: %s", d.name, exc)
    return out
