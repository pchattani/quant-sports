"""The Hardwood's power rankings: data/power/nba.json, data/power/wnba.json and the site index data/power.json
(the shape is oddsmarkets/common/power.py; the kit's power.js draws it on #/<L>/power and on Home).

Read from the payloads this build has just written (no new fetching, no new models), for each league in index.json:

    index.json                  the leagues, each one's current season and phase
    <L>/<S>/season.json         rating_paths (our net rating after every game), the teams (names, colours, conferences),
                                the standings (record, point difference), the season simulation, the postseason series
    <L>/<S>/schedule.json       every finished game, playoffs included (the form and the run)
    <L>/<S>/players.json        every player's season numbers, role (guard, wing, big) and the site's qualifying flag
    <L>/<S>/performers.json     the qualifying rule in words

    build(data_root, now=None) -> {"n", "bytes", "max", "leagues"}   (python -m oddsmarkets.basketball.analytics.power_build)

The rating is the Kalman filter's net rating after each game (rating_paths: the line the team pages chart "through the
season"), points per 100 possessions against an average team, adjusted for opponents and home court. Every snapshot,
now included, comes from that one path, so a move is games and never a switch of model. The season fit the Teams power
board ranks on (season.json ratings) is a different estimate with no history in the payloads: against the path at the
same moment it differs by about one place on average (three at most; NBA, 14 Nov 2026), and a mixed path would have
put that gap into every move.

Snapshots, no look-ahead: a path entry {date, game, net} is the rating after its game (checked on the payloads of
14 Nov 2026: an entry's change correlates +0.90 (NBA) and +0.84 (WNBA) with its own game's margin and +0.04 / +0.03
with the next game's; the Clippers lost by 51 on 9 Nov and their entry for that game fell from -2.90 to -4.32). Path
dates are the local game day. The snapshot at day X takes each team's last entry dated X or earlier, so it uses only
games finished by then. Snapshots run every 7 days back from the latest completed game day D (D, D-7, D-14 ...; D is
"Now"), the oldest dropped while any team has not played yet; the move is the last seven days. Off-season, D is the
last game of the Finals, so the snapshots are the season's last weeks, D is labelled "Final" and the page reads
"Final".

Players: season to date, qualified on the site's own flag, by the site's roles (guards, wings, bigs), ranked on HPM,
the Hardwood plus-minus the Scouting Room and the performers board lead with.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import power as PW

log = logging.getLogger(__name__)

SITE, SPORT = "hardwood", "basketball"
LEAGUES = ("nba", "wnba")
NAME = {"nba": "NBA", "wnba": "WNBA"}
PHASE = {"preseason": "preseason", "regular": "season", "playin": "postseason", "playoffs": "postseason",
         "postseason": "postseason", "offseason": "offseason", "complete": "offseason"}
DASH = "–"
# the names basketball writing already shortens, so a team's name fits beside the climb
SHORT = {"Trail Blazers": "Blazers", "Timberwolves": "Wolves"}
N_SNAPS = PW.MAX_SNAPSHOTS
# (role, key, label, short, stats)
ROLES = [("G", "guards", "Guards", "Guards", ["pts_g", "ast_g", "ts", "tpm_g"]),
         ("W", "wings", "Wings", "Wings", ["pts_g", "reb_g", "ast_g", "ts"]),
         ("B", "bigs", "Bigs", "Bigs", ["pts_g", "reb_g", "blk_g", "ts"])]
STAT = {"pts_g": ("PPG", "1", "Points per game"), "ast_g": ("APG", "1", "Assists per game"),
        "reb_g": ("RPG", "1", "Rebounds per game"), "ts": ("TS%", "pct1", "True shooting percentage"),
        "tpm_g": ("3PM", "1", "Three-pointers made per game"), "stl_g": ("SPG", "1", "Steals per game"),
        "blk_g": ("BPG", "1", "Blocks per game")}
METRIC = {"key": "hpm", "label": "HPM impact", "unit": "pts/100", "fmt": "+1", "dir": "higher",
          "tip": "Hardwood plus-minus: the points per 100 possessions the player adds to the team’s margin against an "
                 "average player, offence plus defence (box-score impact blended with play-by-play plus-minus)."}


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


def season_label(L: str, S: int) -> str:
    return f"{S - 1}-{str(S)[2:]} season" if L == "nba" else f"{S} season"


def snapshots(paths: dict, tids: list[str], last: str = "Now") -> tuple[list[dict], dict, date | None]:
    """[{key, label, date}] (oldest first, the last labelled `last`: "Now", or "Final" off-season) and {tid: [net at
    each]}: every 7 days back from the latest completed game day D, a team's value at day X its last path entry dated X
    or earlier; the oldest days dropped while any team has no entry yet."""
    rows = {}
    for t in tids:
        r = []
        for e in paths.get(t) or []:
            d, n = _day(e.get("date")), PW.num(e.get("net"))
            if d is not None and n is not None:
                r.append((d, n))
        rows[t] = sorted(r, key=lambda x: x[0])
    days = [d for r in rows.values() for d, _ in r]
    if not days:
        return [], {t: [] for t in tids}, None
    D = max(days)
    snaps, out = [], {t: [] for t in tids}
    for k in range(N_SNAPS - 1, -1, -1):
        X = D - timedelta(days=7 * k)
        col = {}
        for t in tids:
            v = None
            for d, n in rows[t]:
                if d > X:
                    break
                v = n
            col[t] = v
        if k and any(v is None for v in col.values()):
            continue
        snaps.append({"key": "now" if k == 0 else "d" + X.isoformat(), "label": last if k == 0 else _label(X), "date": X.isoformat()})
        for t in tids:
            out[t].append(col[t])
    return snaps, out, D


def results(sched: dict | None, tid: str) -> list[str]:
    """The team's finished games, playoffs included, oldest first, as W / L."""
    gs = []
    for g in (sched or {}).get("games") or []:
        if g.get("status") != "post" or g.get("stype") == "pre" or PW.num(g.get("hs")) is None or PW.num(g.get("as")) is None:
            continue
        h, a = str(g.get("home")), str(g.get("away"))
        if tid not in (h, a):
            continue
        us, them = (g["hs"], g["as"]) if tid == h else (g["as"], g["hs"])
        gs.append((str(g.get("date") or ""), str(g.get("id")), "W" if us > them else "L"))
    gs.sort()
    return [x[2] for x in gs]


def streak(res: list[str]) -> str | None:
    if not res:
        return None
    n = 0
    for r in reversed(res):
        if r != res[-1]:
            break
        n += 1
    return f"{res[-1]}{n}"


def playoff_finish(post: dict | None, tid: str) -> tuple[str | None, bool]:
    """('Champions' | 'Finals' | the round it went out in | None (missed), champion?) from the postseason series."""
    ser = [s for s in ((post or {}).get("series") or []) if tid in [str(x) for x in s.get("teams") or []]]
    if not ser:
        return None, False
    last = max(ser, key=lambda s: int(s.get("rnum") or 0))
    final = str(last.get("rkey") or "") == "finals"
    if final and str(last.get("winner")) == tid:
        return "Champions", True
    if final:
        return "Finals", False
    return str(last.get("round") or "Playoffs"), False


def players_block(pl: dict | None, pf: dict | None, info: dict, L: str) -> dict | None:
    if not pl or not isinstance(pl.get("players"), dict):
        return None
    mins = [v.get("min") for v in (pf or {}).get("views") or [] if v.get("min")]
    min_text = mins[0] if mins else (f"{pl['min_floor']} minutes so far" if pl.get("min_floor") else "")
    groups = []
    for role, key, label, short, stats in ROLES:
        rows = []
        for pid, p in pl["players"].items():
            if not isinstance(p, dict) or p.get("role") != role or not p.get("qualified"):
                continue
            tm = str(p.get("team") or "")
            ti = info.get(tm) or {}
            rows.append({"id": pid, "name": p.get("name"), "team": ti.get("abbr") or tm, "colour": ti.get("colour"),
                         "href": f"#/{L}/player/{pid}", "v": p.get("values") or {}})
        st = [{"key": s, "label": STAT[s][0], "fmt": STAT[s][1], "tip": STAT[s][2]} for s in stats]
        g = PW.group(key, label, rows, METRIC, st, short=short, min_text=min_text)
        if g:
            groups.append(g)
    return {"noun": "players", "groups": groups} if groups else None


def league_doc(data_root: Path, ix: dict, L: str, now: str | None) -> dict | None:
    lg = (ix.get("leagues") or {}).get(L) or {}
    S = lg.get("current_season")
    if not S:
        return None
    S = int(S)
    sdir = data_root / L / str(S)
    sj = _read(sdir / "season.json") or {}
    info = {str(k): v for k, v in (sj.get("teams") or lg.get("teams") or {}).items()}
    paths = sj.get("rating_paths") or {}
    if not paths:
        tj = (_read(sdir / "teams.json") or {}).get("teams") or {}
        paths = {t: x.get("rating_path") or [] for t, x in tj.items()}
    tids = sorted(set(info) | set(paths))
    if not tids:
        return None
    phase = PHASE.get(str(lg.get("phase") or sj.get("phase") or ""), "season")
    snaps, rp, D = snapshots(paths, tids, "Final" if phase == "offseason" else "Now")
    if not snaps:
        return None
    rows = {}
    st = sj.get("standings") or {}
    for grp in (st.values() if isinstance(st, dict) else [st]):
        for r in grp or []:
            if r.get("team") is not None:
                rows[str(r["team"])] = r
    sim = ((sj.get("sim") or {}).get("teams") or {}) if isinstance(sj.get("sim"), dict) else {}
    sched = _read(sdir / "schedule.json")
    in_season = phase in ("season", "preseason", "postseason")
    extra = {}
    ents = []
    for t in tids:
        i = info.get(t) or {}
        r, sm = rows.get(t) or {}, sim.get(t) or {}
        res = results(sched, t)
        ent = {"id": t, "name": i.get("name") or t, "short": SHORT.get(i.get("short"), i.get("short")), "abbr": i.get("abbr") or t, "colour": i.get("colour"),
               "href": f"#/{L}/team/{t}", "group": i.get("conference"), "rpath": rp.get(t) or [],
               "form": "".join(res[-5:]) or None, "streak": streak(res)}
        if PW.num(r.get("w")) is not None and PW.num(r.get("l")) is not None:
            ent["record"] = f"{int(r['w'])}{DASH}{int(r['l'])}"
        p_title, p_po = PW.num(sm.get("p_title")), PW.num(sm.get("p_playoffs"))
        if in_season and p_title is not None:
            ent["chance"] = {"label": f"{NAME[L]} title", "p": round(p_title, 4)}
        stats = []
        if PW.num(r.get("pd")) is not None:
            d = int(r["pd"])
            stats.append({"label": "Point diff", "text": ("+" if d > 0 else "−" if d < 0 else "") + str(abs(d))})
        if in_season and PW.num(sm.get("exp_w")) is not None and phase != "postseason":
            stats.append({"label": "Proj. wins", "text": str(round(sm["exp_w"]))})
        if in_season and p_po is not None and phase != "postseason":
            stats.append({"label": "Playoffs", "text": PW.pct_text(p_po)})
        if not in_season or phase == "postseason":
            fin, champ = playoff_finish(sj.get("postseason"), t)
            if phase == "offseason":
                stats.append({"label": "Playoffs", "text": fin or "Missed"})
            if champ:
                extra[t] = [f"Won the {season_label(L, S)[:-7]} {NAME[L]} title"]
        if stats:
            ent["stats"] = stats
        ents.append(ent)
    out = PW.teams_block(ents, snaps, step="week", rating_fmt="+1", extra_notes=extra)
    asof = (sj.get("updated_at") or now or _now())[:10]
    upd = now or sj.get("updated_at") or ix.get("updated_at") or _now()
    return PW.document(site=SITE, sport=SPORT, league=L, label=NAME[L], season=S, season_label=season_label(L, S),
                       updated_at=upd, asof=asof, phase=phase,
                       rating={"label": "Our rating", "short": "Rating", "unit": "points per 100 possessions against an average team", "fmt": "+1",
                               "tip": "Our net rating after each game: how many points per 100 possessions a team is better than an "
                                      "average one, adjusted for opponents and home court and updated game by game (the line on "
                                      "each team page). The Teams power board ranks on the season fit, which can differ by a "
                                      "point or so."},
                       snapshots=snaps, teams=out, step="week", kind="teams", noun="teams", parts=[],
                       players=players_block(_read(sdir / "players.json"), _read(sdir / "performers.json"), info, L),
                       notes=[("Each dated ranking uses only the games finished by the end of that day; Final is the rating after "
                               "the season’s last game, and the move is the season’s last seven days." if phase == "offseason" else
                               "Each dated ranking uses only the games finished by the end of that day; Now adds every game since, "
                               "and the move is the last seven days."),
                              "Players: season to date, qualified on minutes (the rule is under each group)."])


def build(data_root: Path, now: str | None = None) -> dict | None:
    data_root = Path(data_root)
    ix = _read(data_root / "index.json") or {}
    docs = []
    for L in LEAGUES:
        try:
            d = league_doc(data_root, ix, L, now)
        except Exception:  # noqa: BLE001  one league failing never takes the other down
            log.exception("power rankings %s", L)
            d = None
        if d:
            docs.append(d)
    if not docs:
        return None
    upd = now or ix.get("updated_at") or _now()
    return PW.write(data_root, docs, site=SITE, sport=SPORT, updated_at=upd, default="nba")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "docs" / "hardwood" / "data"
    print(build(root))
