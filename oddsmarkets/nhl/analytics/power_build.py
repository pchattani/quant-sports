"""The Rink's power rankings: data/power/nhl.json and the site index data/power.json
(the shape is oddsmarkets/common/power.py; the kit's power.js draws it on #/power and on Home).

Read from the payloads this build has just written (no new fetching, no new models):

    index.json              the clubs (names, colours, divisions), the current season and phase
    <S>/teams.json          our team rating now (units.rating; units.model's goals for and against a game, the
                            offence and defence halves), each club's schedule (results, dates), its simulation
    <S>/season.json         the standings rows (record, points, goals, streak) and the season simulation
    <S>/rating_history.json the team rating at every Monday of the season (rating_history.py)
    <S>/skaters.json        every skater's season numbers with the site's qualifying flag (250 minutes at 5v5 over a
                            full season, prorated by team games)
    <S>/goalies.json        every goalie's, qualified at a quarter of the team's minutes in net

    build(data_root, now=None) -> {"n", "bytes", "max", "leagues"}     (python -m oddsmarkets.nhl.analytics.power_build)

Snapshots, no look-ahead: a rating_history point dated Monday M is a refit of the rating on the games dated before M,
so it is the ranking after the games through the Sunday before. Checked on the 2026-27 payloads (14 Nov 2026): a
club's change from one Monday point to the next correlates +0.68 with its goal difference in the games between them,
+0.35 with the Sunday's games alone and -0.08 with the games on the later Monday itself; Carolina beat Winnipeg 7-0 on
Sunday 1 Nov and their 2 Nov points moved +0.12 and -0.16. Each Monday point is a snapshot, labelled with its date.
The last snapshot is now (units.rating, the published fit). The move must cover a full week of games: a Monday point
counts only when its games end at least seven days before the latest completed game (M <= D - 6), so the week in
play folds into now and the move reads against the Monday before it (seven to thirteen days of games, never the one
or two games since a Monday). Off-season, D is the last game of the season, so the snapshots are its last weeks.
The weekly points refit the same model without builder B's season-to-date goalie table, which moves a club by at
most one place against the published rating (rating_history.py).

Players: season to date, qualified on the site's own flag; skaters ranked on Rink value per 60 (GAR per 60, the
Scouting Room's default sort), goalies on goals saved above expected (the Scouting Room's goalie lead).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import power as PW

log = logging.getLogger(__name__)

SITE, SPORT, LEAGUE = "rink", "hockey", "nhl"
PHASE = {"preseason": "preseason", "regular": "season", "playoffs": "postseason", "postseason": "postseason",
         "offseason": "offseason", "complete": "offseason"}
DASH = "–"
TWO_WORD = ("Maple Leafs", "Blue Jackets", "Red Wings", "Golden Knights")
# the names hockey writing already shortens, so a club's name fits beside the climb (eight letters at most)
NICK = {"Hurricanes": "Canes", "Avalanche": "Avs", "Lightning": "Bolts", "Canadiens": "Habs", "Islanders": "Isles",
        "Predators": "Preds", "Blackhawks": "Hawks", "Blue Jackets": "Jackets", "Maple Leafs": "Leafs",
        "Golden Knights": "Knights", "Red Wings": "Wings"}

# skater groups: (key, label, short, positions, stats)
SKATERS = [
    ("c", "Centres", "C", {"C"}, ["gar", "p", "p60", "fo_pct"]),
    ("w", "Wingers", "W", {"L", "R"}, ["gar", "p", "g", "p60"]),
    ("d", "Defencemen", "D", {"D"}, ["gar", "p", "toi_gp", "adj_xgf_pct"]),
]
GOALIE_STATS = ["gsax100", "sv_pct", "gp", "w", "qs_pct"]
# stat key -> (label, fmt, unit, tip)
STAT = {
    "gar": ("GAR", "+1", "goals", "Goals above replacement, season to date"),
    "p": ("Pts", "0", None, "Points"),
    "g": ("G", "0", None, "Goals"),
    "p60": ("P/60", "2", None, "Points per 60 minutes, all situations"),
    "fo_pct": ("FO%", "pct1", None, "Faceoffs won per faceoff taken"),
    "toi_gp": ("TOI/GP", "1", "min", "Minutes a game, all situations"),
    "adj_xgf_pct": ("xGF%", "pct1", None, "On-ice share of 5-on-5 expected goals, score- and venue-adjusted"),
    "gsax100": ("GSAx/100", "+2", None, "Goals saved above expected per 100 unblocked shots faced"),
    "sv_pct": ("SV%", "pct1", None, "Save percentage"),
    "gp": ("GP", "0", None, "Games played"),
    "w": ("W", "0", None, "Wins"),
    "qs_pct": ("QS%", "pct0", None, "Quality starts per start"),
}
SKATER_METRIC = {"key": "gar_60", "label": "Rink value", "unit": "GAR/60", "fmt": "+2", "dir": "higher",
                 "tip": "Goals above a replacement-level player per 60 minutes, from our value model: even-strength play at "
                        "both ends, the power play, the penalty kill, finishing and penalties."}
GOALIE_METRIC = {"key": "gsax", "label": "GSAx", "unit": "goals", "fmt": "+1", "dir": "higher",
                 "tip": "Goals stopped beyond what an average goalie would stop on the same shots, by our expected-goals "
                        "model, season to date."}
SKATER_MIN = "250 minutes at 5v5 over a full season, prorated by team games"
GOALIE_MIN = "a quarter of the team's minutes in net"
POS_SUB = {"L": "LW", "R": "RW"}


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _label(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def _season_label(season: int) -> str:
    s = str(season)
    return f"{s[:4]}-{s[6:]} season" if len(s) == 8 else f"{s} season"


def _short(name: str | None) -> str:
    nm = str(name or "")
    s = next((x for x in TWO_WORD if nm.endswith(" " + x)), None) or (nm.split(" ")[-1] if " " in nm else nm)
    return NICK.get(s, s)


def _letter(r) -> str | None:
    r = str(r or "").upper()
    return "W" if r == "W" else "O" if r in ("OTL", "SOL", "OT") else "L" if r == "L" else None


def finals(sched: list[dict]) -> list[dict]:
    """A club's finished games, oldest first."""
    out = [g for g in sched or [] if g.get("status") == "final" and _letter(g.get("result")) and _day(g.get("date"))]
    out.sort(key=lambda g: (str(g.get("date")), str(g.get("game_id"))))
    return out


def snapshots(teams: dict, rh: dict | None, season: int) -> tuple[list[dict], dict, date | None]:
    """[{key, label, date}] and {abbr: [the rating_history point at each kept Monday]}, plus the latest completed game
    date D. A Monday M counts when M <= D - 6 (its games end a full week before D); "now" is appended by the caller."""
    last = None
    for t in teams.values():
        for g in finals(t.get("schedule")):
            d = _day(g.get("date"))
            if d and (last is None or d > last):
                last = d
    snaps, paths = [], {a: [] for a in teams}
    if not rh or not rh.get("ok") or int(rh.get("season") or 0) != int(season) or last is None:
        return snaps, paths, last
    hist = rh.get("teams") or {}
    for i, w in enumerate(rh.get("weeks") or []):
        m = _day(w)
        if m is None or m > last - timedelta(days=6):
            continue
        snaps.append({"key": "m" + m.isoformat(), "label": _label(m), "date": m.isoformat()})
        for a in teams:
            h = hist.get(a) or []
            paths[a].append(PW.num(h[i]) if i < len(h) else None)
    return snaps, paths, last


def _rows(pl: dict, info: dict, keep) -> list[dict]:
    rows = []
    for pid, p in (pl or {}).items():
        if not isinstance(p, dict) or not p.get("qualified") or not keep(p):
            continue
        tm = str(p.get("team") or "")
        r = {"id": pid, "name": p.get("name"), "team": tm, "colour": (info.get(tm) or {}).get("colour"),
             "href": f"#/player/{pid}", "v": p.get("values") or {}}
        if POS_SUB.get(p.get("pos")):
            r["sub"] = POS_SUB[p["pos"]]
        rows.append(r)
    return rows


def _stats(keys: list[str]) -> list[dict]:
    out = []
    for k in keys:
        lab, fmt, unit, tip = STAT[k]
        out.append({"key": k, "label": lab, "fmt": fmt, "unit": unit, "tip": tip})
    return out


def players_block(sk: dict | None, gk: dict | None, info: dict) -> dict | None:
    groups = []
    spl = (sk or {}).get("players") or {}
    for key, label, short, pos, stats in SKATERS:
        g = PW.group(key, label, _rows(spl, info, lambda p, pos=pos: p.get("pos") in pos), SKATER_METRIC, _stats(stats),
                     short=short, min_text=SKATER_MIN)
        if g:
            groups.append(g)
    g = PW.group("g", "Goalies", _rows((gk or {}).get("players") or {}, info, lambda p: True), GOALIE_METRIC,
                 _stats(GOALIE_STATS), short="G", min_text=GOALIE_MIN)
    if g:
        groups.append(g)
    return {"noun": "players", "groups": groups} if groups else None


def build(data_root: Path, now: str | None = None) -> dict | None:
    data_root = Path(data_root)
    ix = _read(data_root / "index.json") or {}
    S = ix.get("season")
    if not S:
        return None
    S = int(S)
    sdir = data_root / str(S)
    tj = _read(sdir / "teams.json") or {}
    teams = tj.get("teams") or {}
    if not teams:
        return None
    sj = _read(sdir / "season.json") or {}
    rows = {str(r.get("team")): r for r in ((sj.get("standings") or {}).get("rows") or [])}
    sim = ((sj.get("sim") or {}).get("teams") or {}) if (sj.get("sim") or {}).get("ok") else {}
    info = dict(ix.get("teams") or {})
    phase = PHASE.get(str(sj.get("phase") or tj.get("phase") or ix.get("phase") or ""), "season")
    snaps, paths, last = snapshots(teams, _read(sdir / "rating_history.json"), S)
    snaps.append({"key": "now", "label": "Final" if phase == "offseason" else "Now", "date": last.isoformat() if last else None})
    # the rating's halves: our model's goals for and against a game, about the league's mean (they add up to it)
    mod = {a: ((t.get("units") or {}).get("model") or {}) for a, t in teams.items()}
    gf = [PW.num(m.get("gf_g")) for m in mod.values() if PW.num(m.get("gf_g")) is not None and PW.num(m.get("ga_g")) is not None]
    ga = [PW.num(m.get("ga_g")) for m in mod.values() if PW.num(m.get("gf_g")) is not None and PW.num(m.get("ga_g")) is not None]
    mid = (sum(gf) / len(gf) + sum(ga) / len(ga)) / 2 if gf else None
    parts = [{"key": "off", "label": "Offence"}, {"key": "def", "label": "Defence"}] if mid is not None else []
    in_season = phase in ("season", "preseason")
    ents = []
    for a, t in teams.items():
        i = info.get(a) or {}
        u, r, sm = t.get("units") or {}, rows.get(a) or {}, sim.get(a) or t.get("sim") or {}
        now_r = PW.num(u.get("rating")) if PW.num(u.get("rating")) is not None else PW.num(r.get("rating"))
        name = i.get("name") or t.get("name") or a
        res = [_letter(g.get("result")) for g in finals(t.get("schedule"))]
        ent = {"id": a, "name": name, "short": _short(name), "abbr": a, "colour": i.get("colour") or t.get("colour"),
               "href": f"#/team/{a}", "group": i.get("division") or t.get("division"), "rpath": paths.get(a, []) + [now_r],
               "form": "".join(res[-5:]) or None, "streak": r.get("streak")}
        if PW.num(r.get("w")) is not None:
            ent["record"] = DASH.join(str(int(x or 0)) for x in (r.get("w"), r.get("l"), r.get("otl")))
        m = mod.get(a) or {}
        if mid is not None and PW.num(m.get("gf_g")) is not None and PW.num(m.get("ga_g")) is not None:
            ent["parts"] = {"off": m["gf_g"] - mid, "def": mid - m["ga_g"]}
        p_cup, p_po = PW.num(sm.get("p_cup") if sm.get("p_cup") is not None else r.get("p_cup")), \
            PW.num(sm.get("p_playoffs") if sm.get("p_playoffs") is not None else r.get("p_playoffs"))
        if in_season and p_cup is not None:
            ent["chance"] = {"label": "Stanley Cup", "p": round(p_cup, 4)}
        stats = []
        if PW.num(r.get("pts")) is not None:
            stats.append({"label": "Points", "text": str(int(r["pts"]))})
        if PW.num(r.get("gf")) is not None and PW.num(r.get("ga")) is not None:
            d = int(r["gf"]) - int(r["ga"])
            stats.append({"label": "Goal diff", "text": ("+" if d > 0 else "−" if d < 0 else "") + str(abs(d))})
        if in_season and p_po is not None:
            stats.append({"label": "Playoffs", "text": PW.pct_text(p_po)})
        if stats:
            ent["stats"] = stats
        ents.append(ent)
    out = PW.teams_block(ents, snaps, parts=parts, step="week", rating_fmt="+2")
    asof = (tj.get("updated_at") or now or _now())[:10]
    upd = now or tj.get("updated_at") or _now()
    doc = PW.document(site=SITE, sport=SPORT, league=LEAGUE, label="NHL", season=S, season_label=_season_label(S),
                      updated_at=upd, asof=asof, phase=phase,
                      rating={"label": "Our rating", "short": "Rating", "unit": "goals a game against an average club", "fmt": "+2",
                              "tip": "How many goals a game better than an average club we think each team is: every game’s expected "
                                     "goals and goals at 5 on 5, on the power play and the penalty kill, and its goaltending, weighted "
                                     "towards recent games, with last season as a starting point that fades as the games come in. "
                                     "Offence and defence are our model’s goals for and against a game about the league’s mean."},
                      snapshots=snaps, teams=out, step="week", kind="teams", noun="teams", parts=parts,
                      players=players_block(_read(sdir / "skaters.json"), _read(sdir / "goalies.json"), info),
                      notes=[("Each dated ranking refits our rating on the games played before that Monday; Final is the rating "
                              "at the season’s end, and the move compares it with the last Monday at least a week of games before."
                              if phase == "offseason" else
                              "Each dated ranking refits our rating on the games played before that Monday; Now is today’s rating, "
                              "and the move compares it with the last Monday at least a week of games ago."),
                             "Players: season to date, qualified at their position (the rule is under each group)."])
    return PW.write(data_root, [doc], site=SITE, sport=SPORT, updated_at=upd, default=LEAGUE)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "docs" / "rink" / "data"
    print(build(root))
