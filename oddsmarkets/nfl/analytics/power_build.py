"""The Gridiron's power rankings: data/power/nfl.json and the site index data/power.json
(the shape is oddsmarkets/common/power.py; the kit's power.js draws it on #/power and on Home).

Read from the payloads this build has just written (no new fetching):

    index.json          the teams (names, colours, divisions), the current season, phase and week
    <S>/teams.json      our team rating now (values.rating, off_rating, def_rating, st_rating), the weekly rating
                        history [[week, net, off, def]], the record (streak, last five), the simulation's chances
    <S>/season.json     the standings rows (playoff and Super Bowl chances, streak), when teams.json lacks them
    <S>/players.json    every player's season numbers at his position, with the qualifying rule

    build(data_root, now=None) -> {"n", "bytes", "max", "leagues"}     (python -m oddsmarkets.nfl.analytics.power_build)

Snapshots, no look-ahead: a history entry [w, net, ...] is the rating after week w's games (a team's entry moves with
its own result that week; checked on the 2026 payloads: Kansas City lost 3-20 in week 7 and its week-7 entry fell from
7.09 to 5.36), so the snapshot "Wk w" is the ranking after week w. The last snapshot is now (values.rating); a week
still being played folds into it. The move is against the completed week before.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from oddsmarkets.common import power as PW

log = logging.getLogger(__name__)

SITE, SPORT, LEAGUE = "gridiron", "nfl", "nfl"
SHORT = {"Washington Commanders": "Commanders"}

# position groups: (key, label, short, filter, headline metric, stats)
GROUPS = [
    ("qb", "Quarterbacks", "QB", ("QB", None), "composite", ["epa_db", "cpoe", "pass_yds", "pass_td", "ints"]),
    ("rb", "Running backs", "RB", ("RB", None), "value", ["rush_yds", "ypc", "ryoe", "rush_td", "rec_yds"]),
    ("wr", "Wide receivers", "WR", ("WR", None), "value", ["rec_yds", "rec", "rec_td", "yptpa", "target_share"]),
    ("te", "Tight ends", "TE", ("TE", None), "value", ["rec_yds", "rec", "rec_td", "yptpa", "target_share"]),
    ("edge", "Edge rushers", "EDGE", ("DEF", "EDGE"), "def_value", ["sacks", "pressures_pg", "tfl", "tackles"]),
    ("dl", "Interior line", "DL", ("DEF", "DL"), "def_value", ["sacks", "pressures_pg", "tfl", "tackles"]),
    ("lb", "Linebackers", "LB", ("DEF", "LB"), "def_value", ["tackles", "tfl", "sacks", "pd"]),
    ("cb", "Cornerbacks", "CB", ("DEF", "CB"), "def_value", ["pd", "ints", "tackles", "tfl"]),
    ("s", "Safeties", "S", ("DEF", "S"), "def_value", ["tackles", "pd", "ints", "tfl"]),
    ("k", "Kickers", "K", ("K", None), "fg_oe", ["fg_pct", "fg_50", "xp_pct", "fga"]),
    ("p", "Punters", "P", ("P", None), "epa_punt", ["net", "inside20", "punts"]),
]
FMT = {"epa": "+2", "pct": "pct0", "int": "0", "yds": "1", "1": "1", "2": "2", "0": "0"}
SHORT_LABEL = {"epa_db": "EPA/db", "cpoe": "CPOE", "pass_yds": "Pass yds", "pass_td": "Pass TD", "ints": "INT",
               "rush_yds": "Rush yds", "ypc": "Yds/carry", "ryoe": "RYOE/carry", "rush_td": "Rush TD", "rec_yds": "Rec yds",
               "rec": "Rec", "rec_td": "Rec TD", "yptpa": "Yds/team att", "target_share": "Target share", "sacks": "Sacks",
               "pressures_pg": "Sacks+hits/g", "tfl": "TFL", "tackles": "Tackles", "pd": "PD", "fg_pct": "FG%", "fg_50": "50+ made",
               "xp_pct": "XP%", "fga": "FGA", "net": "Net avg", "inside20": "Inside 20", "punts": "Punts"}
PHASE = {"preseason": "preseason", "regular": "season", "postseason": "postseason", "playoffs": "postseason",
         "offseason": "offseason", "complete": "offseason"}


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(rec: dict) -> str | None:
    if not rec or rec.get("w") is None:
        return None
    w, l, t = int(rec.get("w") or 0), int(rec.get("l") or 0), int(rec.get("t") or 0)
    return f"{w}–{l}" + (f"–{t}" if t else "")


def _partial(teams: dict, w: int) -> bool:
    """Week w has games still to play (or under way)."""
    for t in teams.values():
        for g in t.get("schedule") or []:
            if g.get("week") == w and str(g.get("gtype") or "REG") == "REG" and g.get("status") != "final":
                return True
    return False


def _snapshots(teams: dict, week: int | None) -> tuple[list[dict], dict]:
    """[{key, label, date}] and {abbr: [rating at each snapshot]}: one snapshot per completed week (a history entry
    [w, net, ...] is the rating after week w's games: a team's entry moves with its own result that week), the latest
    replaced by now (values.rating). A week still being played is not a snapshot of its own: its games so far count in
    now, which stands in for the last completed week, so the move reads against the week before that, as a weekly
    power ranking does all week long (a Thursday game does not reset every other move to zero)."""
    weeks = sorted({int(h[0]) for t in teams.values() for h in (t.get("history") or []) if h and h[0] is not None})
    if weeks and _partial(teams, weeks[-1]):
        weeks = weeks[:-1]
    by = {a: {int(h[0]): PW.num(h[1]) for h in (t.get("history") or []) if h and len(h) > 1} for a, t in teams.items()}
    for a, h in by.items():                                  # a bye week carries the rating through
        last = None
        for w in range(1, (weeks[-1] if weeks else 0) + 1):
            if h.get(w) is None and last is not None:
                h[w] = last
            last = h.get(w, last)
    now = {a: PW.num((t.get("values") or {}).get("rating")) for a, t in teams.items()}
    snaps = [{"key": f"w{w}", "label": f"Wk {w}", "date": None} for w in weeks]
    paths = {a: [by[a].get(w) for w in weeks] for a in teams}
    if not weeks:
        snaps.append({"key": "now", "label": "Now", "date": None})
        for a in teams:
            paths[a].append(now[a])
        return snaps, paths
    snaps[-1] = {"key": "now", "label": "Now", "date": None}
    for a in teams:
        if now[a] is not None:
            paths[a][-1] = now[a]
    return snaps, paths


def _players(pl: dict, info: dict) -> dict | None:
    if not pl or not isinstance(pl.get("players"), dict):
        return None
    ms = {m["key"]: m for m in pl.get("metrics") or [] if m.get("key")}
    qual = pl.get("qualification") or {}
    groups = []
    for key, label, short, (grp, role), mk, stats in GROUPS:
        rows = []
        for pid, p in pl["players"].items():
            if p.get("group") != grp or (role and p.get("role") != role) or not p.get("qualified"):
                continue
            tm = p.get("team") or ""
            rows.append({"id": pid, "name": p.get("name"), "team": tm, "colour": (info.get(tm) or {}).get("colour"),
                         "href": f"#/player/{pid}", "v": p.get("values") or {}})
        m = ms.get(mk) or {"label": mk}
        metric = {"key": mk, "label": m.get("label") or mk, "fmt": FMT.get(str(m.get("fmt")), "1"),
                  "dir": "lower" if m.get("lower") else "higher", "tip": m.get("desc")}
        st = []
        for s in stats:
            sm = ms.get(s) or {}
            st.append({"key": s, "label": SHORT_LABEL.get(s) or sm.get("label") or s, "fmt": FMT.get(str(sm.get("fmt")), "1"),
                       "tip": sm.get("label")})
        g = PW.group(key, label, rows, metric, st, short=short, min_text=qual.get(grp) or "")
        if g:
            groups.append(g)
    return {"noun": "players", "groups": groups} if groups else None


def build(data_root: Path, now: str | None = None) -> dict | None:
    data_root = Path(data_root)
    ix = _read(data_root / "index.json") or {}
    S = ix.get("season")
    if not S:
        return None
    tj = _read(data_root / str(S) / "teams.json") or {}
    teams = tj.get("teams") or {}
    if not teams:
        return None
    sj = _read(data_root / str(S) / "season.json") or {}
    srow = {}
    for d in sj.get("standings") or []:
        for r in d.get("teams") or []:
            if r.get("team"):
                srow[r["team"]] = r
    info = ix.get("teams") or {}
    week = tj.get("week") or ix.get("week")
    phase = PHASE.get(str(tj.get("phase") or ix.get("phase") or ""), "season")
    snaps, paths = _snapshots(teams, week)
    has_st = any(PW.num((t.get("values") or {}).get("st_rating")) is not None for t in teams.values())
    parts = [{"key": "off", "label": "Offence"}, {"key": "def", "label": "Defence"}] + ([{"key": "st", "label": "Special teams"}] if has_st else [])
    ents = []
    for a, t in teams.items():
        i = info.get(a) or {}
        vals, rec, sim, r = t.get("values") or {}, t.get("record") or {}, t.get("sim") or {}, srow.get(a) or {}
        p_sb = PW.num(r.get("p_sb") if r.get("p_sb") is not None else sim.get("p_sb"))
        p_po = PW.num(r.get("p_playoffs") if r.get("p_playoffs") is not None else sim.get("p_playoffs"))
        last5 = rec.get("last5") or r.get("last5") or []
        ent = {"id": a, "name": t.get("name") or i.get("name") or a, "short": SHORT.get(t.get("name")) or t.get("short"),
               "abbr": a, "colour": t.get("colour") or i.get("colour"), "href": f"#/team/{a}",
               "group": t.get("division") or i.get("division"), "rpath": paths.get(a),
               "record": _record(rec) or _record(r), "form": "".join(last5) or None, "streak": rec.get("streak") or r.get("streak"),
               "parts": {"off": vals.get("off_rating"), "def": vals.get("def_rating"), "st": vals.get("st_rating")}}
        if phase in ("season", "preseason") and p_sb is not None:
            ent["chance"] = {"label": "Super Bowl", "p": round(p_sb, 4)}
        stats = []
        if PW.num(rec.get("diff")) is not None:
            d = int(rec["diff"])
            stats.append({"label": "Point diff", "text": ("+" if d > 0 else "−" if d < 0 else "") + str(abs(d))})
        if phase in ("season", "preseason") and p_po is not None:
            stats.append({"label": "Playoffs", "text": PW.pct_text(p_po)})
        if stats:
            ent["stats"] = stats
        ents.append(ent)
    rows = PW.teams_block(ents, snaps, parts=parts, step="week", rating_fmt="+1")
    asof = (tj.get("updated_at") or now or _now())[:10]
    doc = PW.document(site=SITE, sport=SPORT, league=LEAGUE, label="NFL", season=int(S), season_label=f"{S} season",
                      updated_at=now or tj.get("updated_at") or _now(), asof=asof, phase=phase,
                      rating={"label": "Our rating", "short": "Rating", "unit": "points a game against an average team", "fmt": "+1",
                              "tip": "The points a game we expect a team to beat an average one by on a neutral field, from every play's expected points, adjusted for the opponents faced."},
                      snapshots=snaps, teams=rows, step="week", kind="teams", noun="teams", parts=parts,
                      players=_players(_read(data_root / str(S) / "players.json"), info),
                      notes=["Each week's ranking uses only the games played up to the end of that week; Now adds any games played since.",
                             "Players: season to date, qualified at their position (the rule is under each group)."])
    return PW.write(data_root, [doc], site=SITE, sport=SPORT, updated_at=doc["updated_at"], default=LEAGUE)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "docs" / "gridiron" / "data"
    print(build(root))
