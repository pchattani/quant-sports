"""The Campus's power rankings: data/power/<level>.json for college football, men's and women's basketball and men's
and women's hockey (cfb, mbb, wbb, mch, wch), and the site index data/power.json (default cfb). The shape is
oddsmarkets/common/power.py; the kit's power.js draws it on #/<level>/power and on Home.

Read from the payloads the build has just written (no fetching, no new model):

    index.json                  each level's current season and phase
    <L>/<S>/season.json         the teams (names, colours, conferences), the standings (record, streak, poll rank), our
                                ratings now (rating, off, def), the rating paths (our rating through the season), the
                                season simulation (playoff / NCAA and title chances)
    <L>/<S>/schedule.json       every game's status and day (whether the week after the last snapshot is still in play;
                                football's week numbers for the labels; recent form)
    <L>/<S>/players.json        every player's season numbers with the level's qualifying flag

    build(data_root, now=None) -> {"n", "bytes", "max", "leagues"}        (python -m oddsmarkets.college.power_build)

Snapshots, no look-ahead. Each comes from season.json rating_paths, which is not dated the same way on every level
(checked on the 2026-27 payloads by correlating each team's rating change between two path dates with its results
against our pre-game chance over the games in [a, b) and in (a, b], and on single results):

  - football (football/build.py rating_paths): an entry dated d is the walk-forward rating at the start of a week,
    from the games before d (correlation 0.60 v 0.58; Florida International lost on 20 Oct as a 78% favourite and its
    entries read -10.20 on 13 Oct, -10.18 on 20 Oct, -11.51 on 27 Oct). Weekly: one snapshot per completed week,
    labelled "Wk N" (N = the last week played before d, "Pre" before any). A week still being played (any game in the
    seven days from the last snapshot not final) folds into Now, as on the Gridiron, so a Tuesday game does not reset
    every move to zero; the move is then against the week before.
  - hockey (hockey/build.py rating_paths): every seventh day from the first game day, from the games before that day,
    plus the day after the last game (0.73 v 0.68; Michigan State lost on 12 Nov: 1.05 on 12 Nov, 0.99 on 13 Nov).
    College hockey is played in weekend series, so it is treated as weekly: the same fold rule as football.
  - basketball (hoops/build.py, the Kalman filter's rating at the end of the last game day of each 7-day block,
    games on that day included: 0.585 v 0.540; Clemson lost on 13 Nov: 17.75 on 7 Nov, 15.90 on 13 Nov). Daily: one
    snapshot every 7 days counting back from the latest game day (the latest path entry at or before each date), so
    the move always spans at least a week of games. Early in the season that leaves one snapshot (Now) and the page
    says the climb starts after two.

Now is always season.json `ratings` (the rating on every page). Football's and hockey's last path entry is that same
fit (checked: equal for every team); basketball's path is the Kalman filter and Now the full fit (mean gap 1.5-1.7
points per 100, rank correlation 0.99), so part of a basketball move can be the change of method: the page says so.
Players: season to date, qualified on the level's own rule (football `qualified_rate`, the others `qualified`).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import power as PW

log = logging.getLogger(__name__)

SITE, SPORT, DEFAULT = "campus", "college", "cfb"
LEVELS = ("cfb", "mbb", "wbb", "mch", "wch")
HOCKEY = ("mch", "wch")
# the league labels are the site's level codes (its level switch): Home's league picker is one row of five buttons and
# the long names ("Women's basketball") run it past a phone's width; the site's own chips write them out (cc-power.js)
LABEL = {"cfb": "CFB", "mbb": "MBB", "wbb": "WBB", "mch": "MCH", "wch": "WCH"}
DAY_HOURS = {"cfb": 8, "mbb": 6, "wbb": 6, "mch": 9, "wch": 9}     # each level's game day: UTC minus these hours
AFTER = {"mbb", "wbb"}            # a path entry includes its own day's games (basketball); the others are before it
WEEKLY = {"cfb", "mch", "wch"}    # one snapshot per completed week; basketball is daily (every 7 days back)
PHASE = {"preseason": "preseason", "regular": "season", "conf_champ": "season", "conf_tourneys": "season",
         "bowls": "postseason", "playoff": "postseason", "ncaa": "postseason", "offseason": "offseason"}
NOT_GAMES = ("exh", "pre")

RATING = {
    "cfb": {"label": "Our rating", "short": "Rating", "unit": "points v an average FBS team", "fmt": "+1",
            "tip": "Our opponent-adjusted team rating: the points we expect a team to beat an average FBS team by on a neutral field, from its scoring margins, expected points and success rate, split into offence and defence."},
    "hoops": {"label": "Our rating", "short": "Rating", "unit": "points per 100 possessions v an average D-I team", "fmt": "+1",
              "tip": "Our opponent-adjusted efficiency margin: points per 100 possessions better than an average Division I team on a neutral floor, offence minus defence (each against the national average)."},
    "hockey": {"label": "Our rating", "short": "Rating", "unit": "goals a game v an average D-I team", "fmt": "+2",
               "tip": "Our opponent-adjusted rating: goals a game better than an average Division I team on neutral ice, split into attack and defence."},
}

# position groups: (key, label, short, position, headline, [stats]); stat: (key, label, fmt, tip)
CFB_MIN = {"QB": "12.5 dropbacks a team game", "RB": "6.25 carries a team game", "WR": "2.5 targets a team game",
           "TE": "1.67 targets a team game", "DL": "60% of the team's games", "LB": "60% of the team's games",
           "DB": "60% of the team's games", "K": "0.67 field-goal attempts a team game", "P": "1.67 punts a team game"}
VAL = ("value_pg", "Value per game", "+2", "points a game",
       "Our value model: points a game above a replacement-level player at the position (EPA on the player's plays for skill players, box-score points for defenders and specialists).")
CFB_GROUPS = [
    ("qb", "Quarterbacks", "QB", "QB", VAL, [("pass_yds", "Pass yds", "0"), ("pass_td", "Pass TD", "0"), ("pass_int", "INT", "0"), ("epa_db", "EPA/db", "+2"), ("cmp_pct", "Comp%", "pct1")]),
    ("rb", "Running backs", "RB", "RB", VAL, [("rush_yds", "Rush yds", "0"), ("ypc", "Yds/carry", "1"), ("rush_td", "Rush TD", "0"), ("epa_rush", "EPA/carry", "+2"), ("rec_yds", "Rec yds", "0")]),
    ("wr", "Wide receivers", "WR", "WR", VAL, [("rec_yds", "Rec yds", "0"), ("rec", "Rec", "0"), ("rec_td", "Rec TD", "0"), ("yptpa", "Yds/team att", "2"), ("tgt_share", "Target share", "pct0")]),
    ("te", "Tight ends", "TE", "TE", VAL, [("rec_yds", "Rec yds", "0"), ("rec", "Rec", "0"), ("rec_td", "Rec TD", "0"), ("yptpa", "Yds/team att", "2"), ("tgt_share", "Target share", "pct0")]),
    ("dl", "Defensive line", "DL", "DL", VAL, [("sacks", "Sacks", "1"), ("tfl", "TFL", "1"), ("havoc_pg", "Havoc/g", "2"), ("tkl", "Tackles", "0")]),
    ("lb", "Linebackers", "LB", "LB", VAL, [("tkl", "Tackles", "0"), ("tfl", "TFL", "1"), ("sacks", "Sacks", "1"), ("pd", "PD", "0")]),
    ("db", "Defensive backs", "DB", "DB", VAL, [("pd", "PD", "0"), ("def_int", "INT", "0"), ("tkl", "Tackles", "0"), ("havoc_pg", "Havoc/g", "2")]),
    ("k", "Kickers", "K", "K", VAL, [("fg_pct", "FG%", "pct0"), ("fgm", "FGM", "0"), ("fg_long", "Long", "0"), ("xp_pct", "XP%", "pct0")]),
    ("p", "Punters", "P", "P", ("gross", "Gross average", "1", "yards", "Gross yards a punt."), [("in20_rate", "Inside 20", "pct0"), ("tb_rate", "Touchback%", "pct0")]),
]
BOX = ("r", "Box rating", "+1", "points per 100 possessions",
       "Our box rating: points per 100 possessions above an average Division I player, team-constrained, so a player on a strong team against a strong schedule is credited for it.")
HOOPS_GROUPS = [
    ("g", "Guards", "G", "G", BOX, [("pts", "Pts/g", "1"), ("ast", "Ast/g", "1"), ("ts", "TS%", "pct1"), ("stl", "Stl/g", "1"), ("tov", "TOV/g", "1")]),
    ("f", "Forwards", "F", "F", BOX, [("pts", "Pts/g", "1"), ("reb", "Reb/g", "1"), ("ts", "TS%", "pct1"), ("blk", "Blk/g", "1")]),
    ("c", "Centres", "C", "C", BOX, [("pts", "Pts/g", "1"), ("reb", "Reb/g", "1"), ("blk", "Blk/g", "1"), ("ts", "TS%", "pct1")]),
]
GAR = ("gar_pg", "GAR per game", "+2", "goals a game",
       "Our hockey value model: goals above a replacement-level player (goals created, a damped +/- share, penalties and faceoffs), a game.")
HOCKEY_GROUPS = [
    ("f", "Forwards", "F", "F", GAR, [("g", "G", "0"), ("a", "A", "0"), ("pts", "PTS", "0"), ("sh_pg", "Shots/g", "1")]),
    ("d", "Defence", "D", "D", GAR, [("a", "A", "0"), ("pts", "PTS", "0"), ("pm_rel", "+/- v team", "+1"), ("blk_pg", "Blocks/g", "1")]),
    ("g", "Goalies", "G", "G", ("gsaa", "GSAA", "+1", "goals saved above average", "Goals saved above an average goalie facing the same shots."),
     [("sv_pct", "SV%", "3"), ("gaa", "GAA", "2"), ("gar", "GAR", "+1"), ("so", "Shutouts", "0")]),
]


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _unpack(o):
    from oddsmarkets.college.packing import unpack
    return unpack(o) if o is not None else None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def game_day(L: str, iso) -> date | None:
    """The level's game day of a UTC start (the builders' own convention)."""
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (t - timedelta(hours=DAY_HOURS.get(L, 8))).date()


def _label(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def _signed(v, n: int = 0) -> str:
    v = PW.num(v)
    if v is None:
        return ""
    return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v):.{n}f}"


def _games(sched: dict | None) -> list[dict]:
    return [g for g in ((sched or {}).get("games") or []) if isinstance(g, dict) and g.get("stype") not in NOT_GAMES]


def in_play(L: str, games: list[dict], start: date) -> bool:
    """Is the week after a snapshot still being played: any game in its seven days (from the snapshot's day for a
    before-its-games entry, from the next day for basketball's end-of-day entries) not over?"""
    a = start + timedelta(days=1 if L in AFTER else 0)
    b = a + timedelta(days=7)
    for g in games:
        if g.get("status") not in ("pre", "in"):
            continue
        d = game_day(L, g.get("date"))
        if d is not None and a <= d < b:
            return True
    return False


def week_done(L: str, games: list[dict], d: date) -> int:
    """Football: the last week whose games were all played before day d (0 before any)."""
    weeks = {}
    for g in games:
        if g.get("stype") != "reg" or g.get("week") is None:
            continue
        gd = game_day(L, g.get("date"))
        if gd is None:
            continue
        w = int(g["week"])
        weeks[w] = max(weeks.get(w, gd), gd)
    done = [w for w, last in weeks.items() if last < d]
    return max(done) if done else 0


def snapshot_dates(L: str, paths: dict, games: list[dict]) -> tuple[list[date], date | None]:
    """The path dates to snapshot (oldest first) and the now date (the latest path date: the current fit's)."""
    dates = sorted({x for v in paths.values() for x in (_d(e[0]) for e in v if isinstance(e, list) and e) if x})
    if not dates:
        return [], None
    now_d, cands = dates[-1], dates[:-1]
    if L in WEEKLY:
        if cands and in_play(L, games, cands[-1]):
            cands = cands[:-1]
        return cands, now_d
    picks = []
    for k in range(1, PW.MAX_SNAPSHOTS):
        t = now_d - timedelta(days=7 * k)
        c = max((x for x in cands if x <= t), default=None)
        if c is None:
            break
        if c not in picks:
            picks.append(c)
    return sorted(picks), now_d


def value_at(path: list, d: date):
    """A team's rating at a snapshot: its latest path entry dated d or earlier."""
    best = None
    for e in path or []:
        x = _d(e[0]) if isinstance(e, list) and e else None
        if x is not None and x <= d and PW.num(e[1]) is not None:
            best = PW.num(e[1])
    return best


def _form(L: str, games: list[dict], t: str) -> str | None:
    out = []
    for g in sorted(games, key=lambda g: str(g.get("date") or "")):
        if g.get("status") != "post" or t not in (str(g.get("home")), str(g.get("away"))):
            continue
        hs, as_ = PW.num(g.get("hs")), PW.num(g.get("as"))
        if hs is None or as_ is None:
            continue
        mine, theirs = (hs, as_) if str(g.get("home")) == t else (as_, hs)
        out.append("W" if mine > theirs else "L" if mine < theirs else "T")
    return "".join(out[-5:]) or None


def _record(L: str, r: dict) -> str | None:
    if PW.num(r.get("w")) is None or PW.num(r.get("l")) is None:
        return None
    s = f"{int(r['w'])}–{int(r['l'])}"
    if L in HOCKEY:
        s += f"–{int(PW.num(r.get('t')) or 0)}"
    return s


def _players(L: str, pj: dict | None, teams: dict) -> dict | None:
    if not pj or pj.get("ok") is False:
        return None
    from oddsmarkets.college.performers import _players as cat_players
    P = cat_players(pj)
    if not P:
        return None
    fb, hk = L == "cfb", L in HOCKEY
    qf = "qualified_rate" if fb else "qualified"
    spec = CFB_GROUPS if fb else HOCKEY_GROUPS if hk else HOOPS_GROUPS
    mf = pj.get("min_floor") or {}
    groups = []
    for key, label, short, pos, (mk, ml, mfmt, munit, mtip), stats in spec:
        rows = []
        for pid, p in P.items():
            if not isinstance(p, dict) or p.get("pos") != pos or not p.get(qf, p.get("qualified")):
                continue
            tm = teams.get(str(p.get("team"))) or {}
            rows.append({"id": str(pid), "name": p.get("name") or "", "team": tm.get("abbr") or tm.get("short") or "",
                         "colour": tm.get("colour"), "href": f"#/{L}/player/{pid}", "v": p.get("values") or {}})
        if fb:
            mn = CFB_MIN.get(pos, "")
        elif hk:
            gp = PW.num(mf.get("gp"))
            mn = "a quarter of the most games played (at least 3)" if pos == "G" else (
                f"{int(gp)}+ games (40% of the most played)" if gp else "40% of the most games played")
        else:
            gp, mpg = PW.num(mf.get("gp")), PW.num(mf.get("mpg"))
            mn = f"{int(gp)}+ games and {mpg:g} minutes a game" if gp and mpg else "40% of the season's most games and 10 minutes a game"
        g = PW.group(key, label, rows, {"key": mk, "label": ml, "unit": munit, "fmt": mfmt, "dir": "higher", "tip": mtip},
                     [{"key": k, "label": lab, "fmt": f} for k, lab, f in stats], short=short, min_text=mn)
        if g:
            groups.append(g)
    return {"noun": "players", "groups": groups} if groups else None


def level_doc(data_root: Path, L: str, S, phase_raw: str | None, now: str | None = None) -> dict | None:
    base = Path(data_root) / L / str(S)
    sj = _unpack(_read(base / "season.json"))
    if not isinstance(sj, dict) or sj.get("ok") is False:
        return None
    R = {str(t): r for t, r in (sj.get("ratings") or {}).items() if isinstance(r, dict) and PW.num(r.get("rating")) is not None}
    if not R:
        return None
    teams = {str(t): v for t, v in (sj.get("teams") or {}).items() if isinstance(v, dict)}
    confs = sj.get("conferences") or {}
    srow = {}
    for rows in (sj.get("standings") or {}).values():
        for r in rows or []:
            if isinstance(r, dict) and r.get("team") is not None:
                srow[str(r["team"])] = r
    sim = ((sj.get("sim") or {}).get("teams")) or {}
    games = _games(_unpack(_read(base / "schedule.json")))
    paths = {str(t): v for t, v in (sj.get("rating_paths") or {}).items() if isinstance(v, list)}
    phase = PHASE.get(str(phase_raw or sj.get("phase") or ""), "season")
    fb, hk = L == "cfb", L in HOCKEY
    cands, now_d = snapshot_dates(L, paths, games)
    snaps = []
    for d in cands:
        if fb:
            n = week_done(L, games, d)
            lab = f"Wk {n}" if n else "Pre"
        else:
            lab = _label(d)
        snaps.append({"key": "d" + d.isoformat(), "label": lab, "date": d.isoformat()})
    if fb:                                  # two path dates in one week (a re-pick) keep the later
        keep = {}
        for i, s in enumerate(snaps):
            keep[s["label"]] = i
        idx = sorted(keep.values())
        snaps, cands = [snaps[i] for i in idx], [cands[i] for i in idx]
    snaps.append({"key": "now", "label": "Final" if phase == "offseason" else "Now", "date": now_d.isoformat() if now_d else None})
    avg = 0.0
    if not fb and not hk:                   # basketball: offence minus defence per 100, each against the national average
        os_ = [PW.num(r.get("off")) for r in R.values() if PW.num(r.get("off")) is not None]
        ds_ = [PW.num(r.get("def")) for r in R.values() if PW.num(r.get("def")) is not None]
        avg = ((sum(os_) / len(os_) if os_ else 0) + (sum(ds_) / len(ds_) if ds_ else 0)) / 2
    parts = [{"key": "off", "label": "Attack" if hk else "Offence"}, {"key": "def", "label": "Defence"}]
    field = ("p_cfp", "Playoff") if fb else ("p_ncaa", "NCAA")
    poll = "USCHO" if hk else "AP"
    in_season = phase in ("season", "preseason", "postseason")
    ents = []
    for t, r in R.items():
        tm, st, sm = teams.get(t) or {}, srow.get(t) or {}, sim.get(t) or {}
        if tm.get("member") is False:
            continue
        rpath = [value_at(paths.get(t), d) for d in cands] + [PW.num(r.get("rating"))]
        off, de = PW.num(r.get("off")), PW.num(r.get("def"))
        if fb or hk:
            pts = {"off": off, "def": de}
        else:
            pts = {"off": off - avg if off is not None else None, "def": avg - de if de is not None else None}
        c = confs.get(str(tm.get("conference"))) or {}
        # the school's name ("South Carolina"), as the polls write it: the mascot makes a phone row's name run out
        ent = {"id": t, "name": tm.get("short") or tm.get("name") or t, "short": tm.get("short"), "abbr": tm.get("abbr"), "colour": tm.get("colour"),
               "href": f"#/{L}/team/{t}", "group": c.get("short") or c.get("name") or ("Independent" if tm.get("conference") else None),
               "rpath": rpath, "record": _record(L, st), "form": _form(L, games, t), "streak": st.get("streak"), "parts": pts}
        stats = []
        p_title, p_field = PW.num(sm.get("p_title")), PW.num(sm.get(field[0]))
        if in_season and p_title is not None and p_title >= 0.001:     # a long shot's "<1%" on 300 rows is noise (and bytes)
            ent["chance"] = {"label": "National title", "p": round(p_title, 4)}
        if in_season and p_field is not None:
            stats.append({"label": field[1], "text": PW.pct_text(p_field)})
        a, b = (PW.num(st.get("gf")), PW.num(st.get("ga"))) if hk else (PW.num(st.get("pf")), PW.num(st.get("pa")))
        if a is not None and b is not None:
            stats.append({"label": "Goal diff" if hk else "Point diff", "text": _signed(a - b)})
        rk = PW.num(st.get("rank"))
        if rk:          # the poll rank on the sub-line, as on the Teams page's power board ("8-1 · SEC · AP No. 4")
            ent["group"] = " · ".join(x for x in (ent.get("group"), f"{poll} No. {int(rk)}") if x)
        if stats:
            ent["stats"] = stats[:2]
        ents.append(ent)
    rows = PW.teams_block(ents, snaps, parts=parts, step="week", rating_fmt=RATING["hockey" if hk else "cfb" if fb else "hoops"]["fmt"])
    if phase == "offseason":
        for x in rows:
            x["note"] = str(x.get("note") or "").replace(" this week", " in the final week")
    upd = now or sj.get("updated_at") or _now()
    if fb:
        how = "Each week's ranking is our rating after that week's games, from the games played by then; Now adds any games played since."
    elif hk:
        how = "Each snapshot is our rating going into that day, from the games played before it; Now adds every game since."
    else:
        how = ("Each snapshot is our rating at the end of that day's games, a week or more apart, counting back from the latest. "
               "The earlier points are the team pages' rating path (a running filter); Now is the full current fit, so part of a small move can be the difference between the two.")
    S_lab = f"{S} season" if fb else f"{int(S) - 1}–{str(S)[2:]} season"
    return PW.document(site=SITE, sport=SPORT, league=L, label=LABEL[L], season=int(S), season_label=S_lab, updated_at=upd,
                       asof=upd[:10], phase=phase, rating=RATING["hockey" if hk else "cfb" if fb else "hoops"], snapshots=snaps,
                       teams=rows, step="week", kind="teams", noun="teams", parts=parts,
                       players=_players(L, _unpack(_read(base / "players.json")), teams),
                       notes=[how, "Players: season to date, qualified at their position (the rule is under each group)."])


def build(data_root: Path, now: str | None = None) -> dict | None:
    data_root = Path(data_root)
    ix = _read(data_root / "index.json") or {}
    docs = []
    for L in LEVELS:
        info = (ix.get("levels") or {}).get(L) or {}
        S = info.get("current_season")
        if not S or info.get("ok") is False:
            continue
        try:
            d = level_doc(data_root, L, S, info.get("phase"), now)
        except Exception:  # noqa: BLE001  one level failing never takes the others down
            log.exception("power rankings %s failed", L)
            d = None
        if d and d.get("teams"):
            docs.append(d)
    if not docs:
        return None
    upd = now or ix.get("updated_at") or max(d["updated_at"] for d in docs)
    return PW.write(data_root, docs, site=SITE, sport=SPORT, updated_at=upd, default=DEFAULT)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "docs" / "campus" / "data"
    print(build(root))
