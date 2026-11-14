"""The Paddock's power rankings: data/power/drivers.json, data/power/constructors.json and the site index
data/power.json (the shape is oddsmarkets/common/power.py; the kit's power.js draws them on #/power and on Home).

Read from the payloads this build has just written (no fetching, no new model):

    index.json              the current season, the drivers (code, team) and the constructors (names, colours)
    <Y>/season.json         standings, our Elo now (elo, elo_teammate, elo_quali), the championship simulation
                            (title chances, clinched), the calendar and whether the season is finished
    <Y>/drivers.json        the driver catalogue: the peer floor and `qualified`, the values the groups show, and each
                            driver's race log (finishing position and status by round)
    <Y>/teams.json          the constructors: car pace now, and the drivers who raced for each team in each round (log)
    drivers/<id>.json       each driver's career Elo path, "elo": [[year, round, field Elo, team-mate Elo]], one entry per
                            Grand Prix the driver entered

    build(data_root, now=None) -> {"n", "bytes", "max", "leagues"}     (python -m oddsmarkets.f1.analytics.power_build)

Two league files: "drivers" (the default; kind players) ranked on our field Elo, and "constructors" (kind teams) ranked
on the mean field Elo of the team's race drivers in each round. Both are shown against the grid average at that
snapshot (the mean over the drivers ranked), as the overview's power board shows them, so the list's bar runs either
side of zero; the Elo itself is a stat beside it.

Snapshots, no look-ahead: a career entry [Y, r, elo, ...] is the rating after round r's Grand Prix (checked on the
2026 payloads: Norris won round 20 in Brazil and his round-20 entry rose from 1732.7 to 1740.9; Piastri finished 13th
in Mexico City, round 19, and his round-19 entry fell from 1696.9 to 1687.2), and the last entry equals season.json's
Elo. So the snapshot "R<r>" is the ranking after round r: one per completed Grand Prix of the season, at most ten, the
last replaced by now (season.json's Elo). Sprints are not rated and qualifying does not move the Elo, so a weekend in
progress changes nothing until its Grand Prix is run: the move is always against the Grand Prix before. A driver who
missed a round carries the rating in. A finished season (or one with no round run yet, which shows the last finished
one) is "offseason": its snapshots are the last ten rounds and the last reads "Final".

Groups in place of positions (qualified drivers only: the catalogue's peer floor of starts): Qualifying on our
qualifying Elo, Race pace on the pace against the team-mate (the race driver rating, the car taken out, with its sign
turned so + is faster, as the Value page shows it) and Team-mate battles on our team-mate Elo, with the numbers a fan reads (average qualifying, poles, average finish, points, head-to-heads).
Season to date.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from oddsmarkets.common import power as PW

log = logging.getLogger(__name__)

SITE, SPORT = "paddock", "f1"
# the site's short codes (docs/paddock/assets/app/core.js TEAM_ABBR)
TEAM_ABBR = {"red_bull": "RBR", "rb": "RB", "alphatauri": "AT", "toro_rosso": "STR", "aston_martin": "AMR", "racing_point": "RP",
             "force_india": "FI", "alfa": "ALF", "sauber": "SAU", "haas": "HAA", "alpine": "ALP", "mclaren": "MCL", "mercedes": "MER",
             "ferrari": "FER", "williams": "WIL", "audi": "AUD", "cadillac": "CAD", "renault": "REN", "lotus_f1": "LOT",
             "manor": "MAN", "marussia": "MRS", "caterham": "CAT"}
FINISHED = ("Finished", "Lapped")
# groups: (key, label, short, metric, stats); metric = (key, label, fmt, unit, dir, source, tip), stat = (key, label, fmt,
# unit, source); source "elo" is season.json's elo[driver], "v" the catalogue's values (_groups merges the two)
GROUPS = [
    ("quali", "Qualifying", "Quali",
     ("elo_quali", "Qualifying Elo", "0", "", "higher", "elo",
      "Our Elo on qualifying positions: one-lap pace against the whole grid, car included (1,500 is an average driver)."),
     [("avg_quali", "Avg quali", "1", "", "v"), ("poles", "Poles", "0", "", "v"), ("q3_rate", "Q3 rate", "pct0", "", "v"),
      ("quali_h2h", "Quali H2H", "pct0", "", "v")]),
    ("race", "Race pace", "Race",
     ("pace_tm", "Pace v team-mate", "+3", "% of a lap", "higher", "v",
      "Race pace with the car taken out, from the season's pace model: how much faster (+) or slower than the team-mate per "
      "lap. The race driver rating with its sign turned, as the Value page shows it."),
     [("avg_finish", "Avg finish", "1", "", "v"), ("points", "Points", "0", "", "v"), ("pos_gained", "Places gained", "+1", "", "v"),
      ("net_overtakes", "Net passes", "+1", "", "v")]),
    ("teammate", "Team-mate battles", "Team-mate",
     ("elo_teammate", "Team-mate Elo", "0", "", "higher", "elo",
      "Our Elo updated only on head-to-heads with the team-mate, who had the same car: the cleanest driver signal."),
     [("race_h2h", "Race H2H", "pct0", "", "v"), ("quali_h2h", "Quali H2H", "pct0", "", "v"),
      ("team_points_share", "Team points", "pct0", "", "v")]),
]
STAT_TIP = {"avg_quali": "Mean qualifying position", "q3_rate": "Share of qualifying sessions reaching Q3",
            "quali_h2h": "Qualifying head-to-head against the team-mate",
            "avg_finish": "Mean finishing position over classified finishes", "pos_gained": "Grid slot minus finishing position, per race",
            "net_overtakes": "On-track passes made minus suffered, per race",
            "race_h2h": "Races finished ahead of the team-mate", "team_points_share": "Share of the team's points"}


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _surname(name: str) -> str:
    parts = str(name or "").split()
    return parts[-1] if parts else str(name or "")


def _pts(v) -> str:
    v = PW.num(v)
    if v is None:
        return ""
    return f"{v:.0f}" if abs(v - round(v)) < 1e-9 else f"{v:.1f}"


def _thousands(v) -> str:
    v = PW.num(v)
    return f"{v:,.0f}" if v is not None else "—"


def _finish(row: dict) -> str:
    st = str(row.get("status") or "")
    if st == "Did not start":
        return "DNS"
    if st in FINISHED or st.startswith("+"):
        p = row.get("pos")
        return str(p) if isinstance(p, int) else "—"
    return "Ret"


def _season(data_root: Path, idx: dict) -> tuple[int | None, dict]:
    """The season to rank: the current one once a Grand Prix has been run, else the last finished one."""
    y = idx.get("current_season")
    years = [int(x) for x in idx.get("seasons") or [] if str(x).isdigit()] or ([int(y)] if y else [])
    for yy in sorted({int(y)} | set(years) if y else set(years), reverse=True):
        sj = _read(data_root / str(yy) / "season.json") or {}
        if sj.get("ok") is False or not sj.get("standings"):
            continue
        if int(sj.get("rounds_done") or 0) > 0:
            return yy, sj
    return None, {}


def _done_rounds(sj: dict) -> list[dict]:
    return sorted([c for c in sj.get("calendar") or [] if c.get("status") == "done"], key=lambda c: int(c.get("round") or 0))


def _paths(data_root: Path, y: int, ids: list[str], rounds: list[int]) -> dict[str, list]:
    """{driver: [field Elo after each round in `rounds`]} from the career files, a missed round carrying the rating in
    (None before the driver's first Grand Prix of the season)."""
    out = {}
    for d in ids:
        c = _read(data_root / "drivers" / f"{d}.json") or {}
        by = {}
        for e in c.get("elo") or []:
            if isinstance(e, list) and len(e) >= 3 and e[0] == y and PW.num(e[2]) is not None:
                by[int(e[1])] = float(e[2])
        row, last = [], None
        for r in rounds:
            if r in by:
                last = by[r]
            row.append(last)
        out[d] = row
    return out


LOWER = ("Won", "Lost", "Up", "Down", "Best", "Worst", "New", "In", "On", "Second", "Third", "Clinched", "Gained", "Dropped",
         "Top", "Lowest", "Fastest", "Slowest")


def _place(rank: int, n: int, best: str, worst: str) -> str | None:
    """'Best x' / '3rd-best x' for the top three of n, 'Lowest x' / '2nd-lowest x' for the bottom two (n >= 8)."""
    if rank is None:
        return None
    if rank <= 3:
        return (best[0].upper() + best[1:]) if rank == 1 else f"{PW.ordinal(rank)}-{best}"
    if n >= 8 and rank >= n - 1:
        w = n - rank + 1
        return (worst[0].upper() + worst[1:]) if w == 1 else f"{PW.ordinal(w)}-{worst}"
    return None


def _trend(first, last, since: str) -> str | None:
    if first is None or last is None or not since:
        return None
    d = last - first
    if abs(d) < 5:
        return None
    return ("Gained " if d > 0 else "Dropped ") + f"{abs(d):.0f} Elo points since {since}"


def _tidy(rows: list[dict]) -> None:
    """A note's later clauses start in lower case (power.note_for lowers only its own words)."""
    for t in rows:
        parts = str(t.get("note") or "").split("; ")
        for i in range(1, len(parts)):
            if parts[i].split(" ")[0] in LOWER:
                parts[i] = parts[i][0].lower() + parts[i][1:]
        if t.get("note"):
            t["note"] = "; ".join(parts)


def _runs(log_rows: list[dict], name_of_last: str | None) -> list[str]:
    """Plain clauses on a driver's recent Grands Prix (newest last): a winning or podium run, a points run, the last
    race when it was a podium."""
    rows = [r for r in log_rows if r.get("status") != "Did not start"]
    if not rows:
        return []

    def run(test):
        n = 0
        for r in reversed(rows):
            if not test(r):
                break
            n += 1
        return n
    won = run(lambda r: r.get("pos") == 1 and _finish(r) == "1")
    pod = run(lambda r: isinstance(r.get("pos"), int) and r["pos"] <= 3 and _finish(r) not in ("Ret", "DNS"))
    pts = run(lambda r: (PW.num(r.get("points")) or 0) > 0)
    out = []
    if won >= 2:
        out.append(f"Won the last {won} Grands Prix")
    elif won == 1 and name_of_last:
        out.append(f"Won the {name_of_last}")
    elif pod >= 3:
        out.append(f"On the podium in each of the last {pod} races")
    elif pod >= 1 and name_of_last:
        out.append(("Second" if rows[-1].get("pos") == 2 else "Third") + f" at the {name_of_last}")
    if pts >= 5 and won < 2 and pod < 3:
        out.append(f"In the points {pts} races running")
    return out


def build(data_root: Path, now: str | None = None) -> dict | None:
    data_root = Path(data_root)
    idx = _read(data_root / "index.json") or {}
    y, sj = _season(data_root, idx)
    if not y:
        return None
    dcat = _read(data_root / str(y) / "drivers.json") or {}
    tcat = _read(data_root / str(y) / "teams.json") or {}
    D = {str(k): v for k, v in (dcat.get("drivers") or {}).items()} if dcat.get("ok", True) else {}
    TC = {str(k): v for k, v in (tcat.get("teams") or {}).items()} if tcat.get("ok", True) else {}
    finished = bool(sj.get("finished"))
    phase = "offseason" if finished or y != idx.get("current_season") else "season"
    done = _done_rounds(sj)
    rounds = [int(c["round"]) for c in done][-PW.MAX_SNAPSHOTS:]
    race_name = {int(c["round"]): c.get("name") for c in done}
    last_label = "Final" if phase == "offseason" else "Now"
    snaps = [{"key": f"r{r}", "label": f"R{r}", "date": next((c.get("date") for c in done if int(c["round"]) == r), None)} for r in rounds]
    if snaps:
        snaps[-1] = dict(snaps[-1], key="now" if phase != "offseason" else "final", label=last_label)
    else:
        snaps = [{"key": "now", "label": last_label, "date": None}]
    teams_i = {}
    for k, v in (sj.get("teams") or {}).items():
        teams_i[k] = dict(v)
    if y == idx.get("current_season"):
        for k, v in (idx.get("teams") or {}).items():
            teams_i.setdefault(k, {}).update({x: v[x] for x in ("name", "colour") if v.get(x)})
    drivers_i = (idx.get("drivers") or {}) if y == idx.get("current_season") else {}
    names = sj.get("names") or {}
    elo_now = {str(k): v or {} for k, v in (sj.get("elo") or {}).items()}
    dst = {str(r["driver"]): r for r in (sj.get("standings") or {}).get("drivers") or []}
    tst = {str(r["team"]): r for r in (sj.get("standings") or {}).get("constructors") or []}
    champ = sj.get("championship") or {}
    peer_floor = dcat.get("peer_floor")
    # the ranked drivers: the catalogue's qualified race drivers (the peer floor), else everyone in the standings
    ranked = [d for d in dst if (D.get(d) or {}).get("qualified")] or list(dst)
    ranked = [d for d in ranked if PW.num(elo_now.get(d, {}).get("elo")) is not None]
    hist = _paths(data_root, y, ranked, rounds)
    n_s = len(snaps)
    paths = {}
    for d in ranked:
        row = (hist.get(d) or [None] * n_s)[:n_s]
        row += [None] * (n_s - len(row))
        row[-1] = PW.num(elo_now[d].get("elo"))
        paths[d] = row
    avg = []
    for i in range(n_s):
        xs = [paths[d][i] for d in ranked if paths[d][i] is not None]
        avg.append(sum(xs) / len(xs) if xs else None)

    def rel(v, i):
        return v - avg[i] if v is not None and avg[i] is not None else None

    def team_name(t):
        return str((teams_i.get(t) or {}).get("name") or t.replace("_", " ").title()).replace(" F1 Team", "")

    def title_line(kind: str, cid: str) -> str | None:
        """The champion's line: the title won (a finished season) or clinched (the magic number reached)."""
        c = (champ.get(kind) or {}).get(cid) or {}
        row = (dst if kind == "drivers" else tst).get(cid) or {}
        what = "drivers’" if kind == "drivers" else "constructors’"
        if finished and row.get("pos") == 1:
            return f"{y} {what} champion" + ("s" if kind == "constructors" else "")
        if c.get("clinched"):
            return f"Clinched the {y} {what} title"
        return None

    def chance(kind: str, cid: str, ent: dict):
        c = (champ.get(kind) or {}).get(cid) or {}
        p = PW.num(c.get("p_title"))
        if title_line(kind, cid):
            ent.setdefault("stats", []).insert(0, {"label": "Title", "text": "Champion" if kind == "drivers" else "Champions"})
        elif phase == "season" and p is not None and p >= 0.005 and not c.get("eliminated"):
            ent["chance"] = {"label": "Title", "p": round(min(p, 0.9999), 4)}

    def lead(rows: list[dict], kind: str):
        """The champion's line leads its note, with the most telling other clause."""
        for t in rows:
            ln = title_line(kind, t["id"])
            if ln:
                rest = str(t.get("note") or "").rstrip(".").split("; ")[0]
                t["note"] = ln + ("; " + rest if rest and not rest.startswith("Clinched") else "") + "."

    # discipline ranks among the ranked drivers (qualifying Elo, race driver rating, team-mate Elo)
    disc = {"elo_quali": PW._ranks({d: (elo_now.get(d) or {}).get("elo_quali") for d in ranked}),
            "elo_teammate": PW._ranks({d: (elo_now.get(d) or {}).get("elo_teammate") for d in ranked}),
            "driver_effect": PW._ranks({d: ((D.get(d) or {}).get("values") or {}).get("driver_effect") for d in ranked if (D.get(d) or {}).get("qualified")}, higher=False)}
    disc_words = {"elo_quali": ("best qualifying Elo on the grid", "lowest qualifying Elo"),
                  "elo_teammate": ("best team-mate Elo on the grid", "lowest team-mate Elo"),
                  "driver_effect": ("best race pace with the car taken out", "slowest race pace with the car taken out")}
    since = snaps[0]["label"] if len(snaps) > 1 else ""

    # ── drivers
    ents = []
    for d in ranked:
        cat = D.get(d) or {}
        row = dst.get(d) or {}
        info = drivers_i.get(d) or {}
        nm = info.get("name") or cat.get("name") or names.get(d) or d.replace("_", " ").title()
        tm = row.get("team") or cat.get("team") or info.get("team")
        rpath = [rel(v, i) for i, v in enumerate(paths[d])]
        logs = sorted([r for r in cat.get("log") or [] if isinstance(r.get("round"), int)], key=lambda r: r["round"])
        last5 = [_finish(r) for r in logs if r.get("status") != "Did not start"][-5:]
        stats = [{"label": "Elo", "text": _thousands(elo_now[d].get("elo"))}]
        if row.get("wins") is not None:
            stats.append({"label": "Wins", "text": str(row.get("wins"))})
        if last5:
            stats.append({"label": "Last five", "text": " · ".join(last5)})
        pos, pts = row.get("pos"), row.get("points")
        last_r = logs[-1]["round"] if logs else None
        extra = _runs(logs, race_name.get(last_r) if last_r == (rounds[-1] if rounds else None) else None)
        for k, (bw, ww) in disc_words.items():
            c = _place(disc[k].get(d), len(disc[k]), bw, ww)
            if c:
                extra.append(c)
        tr = _trend(paths[d][0], paths[d][-1], since)
        if tr:
            extra.append(tr)
        ent = {"id": d, "name": nm, "short": _surname(nm), "abbr": cat.get("code") or info.get("code") or _surname(nm)[:3].upper(),
               "colour": (teams_i.get(tm) or {}).get("colour"), "href": f"#/driver/{d}", "group": team_name(tm) if tm else None,
               "rpath": rpath, "record": (f"{PW.ordinal(pos)}, {_pts(pts)} pts" if pos and pts is not None else None),
               "stats": stats}
        chance("drivers", d, ent)
        ent["_extra"] = extra
        ents.append(ent)
    extra_d = {e["id"]: e.pop("_extra") for e in ents}
    rating_d = {"label": "Our rating", "short": "Elo", "unit": "Elo points against the grid average", "fmt": "+0",
                "tip": "Our field Elo after every Grand Prix: the finishing order against the whole grid, car and driver together, "
                       "shown against the average of the drivers ranked here (the Elo itself is beside it)."}
    drows = PW.teams_block(ents, snaps, step="race", rating_fmt="+0", extra_notes=extra_d)
    lead(drows, "drivers")
    _tidy(drows)
    asof = str(sj.get("updated_at") or now or _now())[:10]
    upd = now or sj.get("updated_at") or _now()
    notes = [("Each snapshot is the ranking after that Grand Prix, from our Elo after the race; " +
              ("Final is where the season ended." if phase == "offseason" else "Now is the latest rating.") +
              " Sprints are not rated, so a weekend moves the ranking only once its Grand Prix is run."),
             f"Drivers ranked: the race drivers with {peer_floor}+ starts this season." if peer_floor else "",
             "Groups: season to date, the same drivers; the rule is under each group."]
    ddoc = PW.document(site=SITE, sport=SPORT, league="drivers", label="Drivers", season=y, season_label=f"{y} season",
                       updated_at=upd, asof=asof, phase=phase, rating=rating_d, snapshots=snaps, teams=drows, step="race",
                       kind="players", noun="drivers", players=_groups(D, elo_now, teams_i, peer_floor),
                       notes=[n for n in notes if n])

    # ── constructors: the mean field Elo of the drivers who raced for the team in each round
    by_round_drivers: dict[str, dict[int, list[str]]] = {}
    for t, v in TC.items():
        for lg in v.get("log") or []:
            if isinstance(lg.get("round"), int) and lg.get("drivers"):
                by_round_drivers.setdefault(t, {})[lg["round"]] = [str(x) for x in lg["drivers"]]
    listed = {(t, r) for t, rb in by_round_drivers.items() for r in rb}
    for d, cat in D.items():                                  # fallback, for a round teams.json lacks: the drivers' own logs
        for lg in cat.get("log") or []:
            if (isinstance(lg.get("round"), int) and lg.get("team") and lg.get("status") != "Did not start"
                    and (str(lg["team"]), lg["round"]) not in listed):
                lst = by_round_drivers.setdefault(str(lg["team"]), {}).setdefault(lg["round"], [])
                if d not in lst:
                    lst.append(d)
    who = set()
    for t in by_round_drivers:
        for r in rounds:
            who.update(by_round_drivers[t].get(r) or [])
    for t in tst:                                             # the latest line-ups (now)
        rb = by_round_drivers.get(t) or {}
        who.update(rb.get(max(rb, default=None)) or [d for d, x in dst.items() if x.get("team") == t])
    allh = _paths(data_root, y, sorted(who | set(ranked)), rounds)
    for d in allh:
        row = (allh[d] or [None] * n_s)[:n_s]
        row += [None] * (n_s - len(row))
        if PW.num(elo_now.get(d, {}).get("elo")) is not None:
            row[-1] = PW.num(elo_now[d]["elo"])
        allh[d] = row
    car_rank = PW._ranks({t: ((TC.get(t) or {}).get("values") or {}).get("car_pace_latest") for t in tst}, higher=False)
    tents = []
    for t in tst:
        row = tst.get(t) or {}
        rb = by_round_drivers.get(t) or {}
        last_r = max(rb, default=None)
        lineup = rb.get(last_r) or [d for d, x in dst.items() if x.get("team") == t]
        rp, raw = [], []
        for i in range(n_s):
            ds = rb.get(rounds[i]) if rounds and i < len(rounds) else None
            if not rounds or i == n_s - 1:
                ds = lineup                                   # now: the team's latest line-up on its current Elo
            vals = [allh[d][i] for d in ds or [] if d in allh and i < len(allh[d]) and allh[d][i] is not None]
            m = sum(vals) / len(vals) if vals else None
            raw.append(m)
            rp.append(rel(m, i))
        tv = ((TC.get(t) or {}).get("values") or {})
        stats = [{"label": "Team Elo", "text": _thousands(raw[-1])}]
        car = PW.num(tv.get("car_pace_latest"))
        if car is not None:                                   # the site's sign: + is faster
            stats.append({"label": "Car pace", "text": ("+" if car < 0 else "−" if car > 0 else "") + f"{abs(car):.2f}%"})
        if row.get("wins") is not None:
            stats.append({"label": "Wins", "text": str(row.get("wins"))})
        extra = []
        if done and done[-1].get("winner_team") == t:
            lc = done[-1]
            extra.append(f"Won the {lc.get('name')} with {_surname(names.get(lc.get('winner')) or str(lc.get('winner') or '').replace('_', ' ').title())}")
        c = _place(car_rank.get(t), len(car_rank), "fastest car on race pace now", "slowest car on race pace now")
        if c:
            extra.append(c.replace("Best", "Fastest"))
        tr = _trend(raw[0], raw[-1], since)
        if tr:
            extra.append(tr)
        ent = {"id": t, "name": team_name(t), "short": team_name(t), "abbr": TEAM_ABBR.get(t) or team_name(t)[:3].upper(),
               "colour": (teams_i.get(t) or {}).get("colour"), "href": f"#/team/{t}",
               "group": " & ".join(_surname(names.get(d) or d.replace("_", " ").title()) for d in lineup) or None,
               "rpath": rp, "record": (f"{PW.ordinal(row['pos'])}, {_pts(row.get('points'))} pts" if row.get("pos") else None),
               "stats": stats, "_extra": extra}
        chance("constructors", t, ent)
        ent["stats"] = ent["stats"][:3]
        tents.append(ent)
    extra_t = {e["id"]: e.pop("_extra") for e in tents}
    trows = PW.teams_block(tents, snaps, step="race", rating_fmt="+0", extra_notes=extra_t)
    lead(trows, "constructors")
    _tidy(trows)
    rating_t = {"label": "Our rating", "short": "Elo", "unit": "the drivers’ mean Elo against the grid average", "fmt": "+0",
                "tip": "The mean of our field Elo for the team’s race drivers after every Grand Prix (car and drivers together), "
                       "against the average of the drivers ranked on the Drivers list. The team Elo itself is beside it."}
    tdoc = PW.document(site=SITE, sport=SPORT, league="constructors", label="Constructors", season=y, season_label=f"{y} season",
                       updated_at=upd, asof=asof, phase=phase, rating=rating_t, snapshots=snaps, teams=trows, step="race",
                       kind="teams", noun="constructors", players=None,
                       notes=[notes[0], "A team’s rating in a round is the mean Elo of the drivers who raced for it in that round."])
    return PW.write(data_root, [ddoc, tdoc], site=SITE, sport=SPORT, updated_at=upd, default="drivers")


def _groups(D: dict, elo_now: dict, teams_i: dict, peer_floor) -> dict | None:
    groups = []
    for key, label, short, m, stats in GROUPS:
        mk, mlab, mfmt, munit, mdir, msrc, mtip = m
        rows = []
        for d, cat in D.items():
            if not cat.get("qualified"):
                continue
            vals = dict(cat.get("values") or {})
            for k in ("elo", "elo_teammate", "elo_quali"):
                if PW.num((elo_now.get(d) or {}).get(k)) is not None:
                    vals[k] = elo_now[d][k]
            if PW.num(vals.get("driver_effect")) is not None:          # + is faster, as the Value page shows it
                vals["pace_tm"] = -float(vals["driver_effect"])
            tm = cat.get("team")
            rows.append({"id": d, "name": cat.get("name") or d, "team": TEAM_ABBR.get(tm) or str(tm or "")[:3].upper(),
                         "colour": (teams_i.get(tm) or {}).get("colour"), "href": f"#/driver/{d}", "v": vals})
        metric = {"key": mk, "label": mlab, "unit": munit, "fmt": mfmt, "dir": mdir, "tip": mtip}
        st = [{"key": k, "label": lab, "fmt": f, "unit": u, "tip": STAT_TIP.get(k)} for k, lab, f, u, _src in stats]
        g = PW.group(key, label, rows, metric, st, short=short,
                     min_text=f"{peer_floor}+ Grand Prix starts" if peer_floor else "")
        if g:
            groups.append(g)
    # F1 has disciplines, not positions: the page and Home take these words (power.js reads players.head and .cols)
    head = {"kicker": "Drivers by discipline", "title": "Best and worst in every discipline", "home": "by discipline", "chips": "Discipline",
            "sub": "Every dot is a qualified driver on the discipline’s headline number, worse to the left, better to the right; "
                   "the top three in their team colour, the bottom three in coral. Tap a discipline for its top five and bottom three."}
    return {"noun": "drivers", "head": head, "cols": {"player": "Driver"}, "groups": groups} if groups else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "docs" / "paddock" / "data"
    print(build(root))
