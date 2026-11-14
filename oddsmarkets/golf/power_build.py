"""The Quant Green's power rankings: data/power/men.json and data/power/women.json, and the site index data/power.json
(the shape is oddsmarkets/common/power.py; the kit's power.js draws them on #/power and on Home).

Read from the payloads this build has just written (no new fetching, no new model):

    index.json            this week's events per tour (status, the headline chance), the build time
    rankings.json         our rating now per stream (men: PGA Tour, DP World Tour, LIV and Korn Ferry on one scale;
                          women: the LPGA), with the decayed rounds behind it, 12 months' results, the last five starts
    players/<pid>.json    each ranked player's rating history [[event start, rating, event id]] and form
                          [[event start, strokes gained, rounds, rating]]; the events with finishes
    scout/<stream>.json   the Scouting Room's two-year numbers: the strokes-gained categories (men, from PGA Tour season
                          statistics), the scoring splits, the regulars flag (q: 30+ rounds in two years)
    events/<id>.json      this week's events: each player's chance to win (live once the event has live chances)

    build(data_root, now=None) -> {"n", "bytes", "max", "leagues"}     (python -m oddsmarkets.golf.power_build <data>)

Snapshots: one per completed event week (Monday to Sunday), the ranking after that week's events, the last one replaced
by now (rankings.json); at most ten. A history entry is the rating a player carried INTO that event (checked on the
14 Nov 2026 payloads: Blades Brown won the World Wide Technology Championship, 5-8 Nov, at +3.53 a round; his entry
for it reads 0.38 and his rating now is 0.49; Jon Rahm won in Abu Dhabi the same week, entry 1.59, now 1.70), so a
player's rating after week W is the entry of his first start after W (all his rounds before it and none after),
or his rating now if he has not played since. A week with an event not yet final is not a snapshot: its finished
events fold into now (the ratings skip unfinished events), so the move reads against the last completed week before.
A player counts at a snapshot only if he was rankable then (rankings.json's rule: min_weight decayed rounds, 20 rounds,
a round in the last active_days), the weight rebuilt from today's by taking out the rounds since, decayed at the
model's half-life. Ranks at past snapshots are among the players ranked today (the ranking keeps 500 men and every
active woman, so the top 100 lose nothing to it). Residue: a past snapshot's value is centred and decayed on the date
of the player's next start, not the snapshot day (no result after the snapshot enters it; the centring moves about a
hundredth of a stroke a week).

Groups: the men's strokes-gained categories (our estimate from PGA Tour season statistics: off the tee, approach,
around the green, putting), regulars with the statistics; the LPGA has no season statistics, so its groups are the
scoring splits the site has for every player (rounds 1-2, the weekend, front and back nine). The ranked list carries
no parts: a quarter of the men's top 100 have no PGA Tour statistics, and the LPGA none.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import power as PW

log = logging.getLogger(__name__)

SITE, SPORT = "green", "golf"
STREAMS = {"men": ("pga", "eur", "liv", "ntw"), "women": ("lpga",)}
LABEL = {"men": "Men’s tours", "women": "LPGA"}
CENTRE = {"men": "an average PGA Tour player", "women": "an average LPGA Tour player"}
TOUR_SHORT = {"pga": "PGA", "eur": "DPWT", "liv": "LIV", "lpga": "LPGA", "ntw": "KFT"}
TOUR_COL = {"pga": "#1f4fd8", "eur": "#0f7b5c", "liv": "#5b2a86", "ntw": "#8a5a12", "lpga": "#a2244f"}   # core.js TOUR_COL
TOP = 100
HALF_LIFE = 270.0          # the rating's half-life in days (model.json params; read from there when present)
MIN_ROUNDS = 20            # pages.PLAYER_MIN_ROUNDS: rounds before a player is rated on the ranking
# colours that tell the lines apart (the kit's categorical slots, then two more): a golfer has no team colour, and a
# tour colour would paint most of the men's top ten one blue and the whole LPGA one red
PALETTE = ["#7d93ff", "#ff6a4d", "#5ec8f0", "#c39be8", "#8fd16a", "#f28fb5", "#d9b38c", "#ffb84d", "#3fd4b4", "#b0bccf"]
MISSED = ("cut", "wd", "dq", "mdf", "dns")
SPONSOR = (" pres. by ", " presented by ", " driven by ", " powered by ", " hosted by ", " supported by ")

# groups: (key, label, short, metric id, metric label, unit, stats [(id, label, fmt, unit)]); the tip under each
# table carries the full definition, so the labels stay short enough for a table head
SG = ("sg", "SG/rd", "+2", "")
GROUPS = {
    "men": [
        ("ott", "Off the tee", "OTT", "c_ott", "SG off the tee, est.", "strokes/rd",
         [("dist", "Distance", "1", "yds"), ("acc", "Fairways", "pct0", ""), SG]),
        ("app", "Approach", "APP", "c_app", "SG approach, est.", "strokes/rd",
         [("gir", "Greens", "pct0", ""), ("h4", "Par 4s", "+3", ""), SG]),
        ("arg", "Around the green", "ARG", "c_arg", "SG around the green, est.", "strokes/rd",
         [("sand", "Sand saves", "pct0", ""), ("bog", "Bogey+", "pct1", ""), SG]),
        ("putt", "Putting", "PUTT", "c_putt", "SG putting, est.", "strokes/rd",
         [("ppg", "Putts/GIR", "3", ""), ("bird", "Birdie+", "pct1", ""), SG]),
    ],
    "women": [
        ("r12", "Rounds 1 and 2", "R1-2", "sg_e", "SG, rounds 1-2", "strokes/rd",
         [SG, ("cut", "Cuts made", "pct0", ""), ("sd", "Spread", "2", "")]),
        ("wknd", "The weekend", "Wknd", "sg_w", "SG, weekend", "strokes/rd",
         [SG, ("t10", "Top 10s", "pct0", ""), ("win", "Wins", "pct1", "")]),
        ("front", "Front nine", "Front", "sg_f", "SG, front nine", "strokes/nine",
         [SG, ("sg_b", "Back nine", "+2", ""), ("great", "Great rds", "pct0", "")]),
        ("back", "Back nine", "Back", "sg_b", "SG, back nine", "strokes/nine",
         [SG, ("sg_f", "Front nine", "+2", ""), ("poor", "Poor rds", "pct0", "")]),
    ],
}


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


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _label(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def short_event(name: str) -> str:
    n = str(name or "")
    low = n.lower()
    for s in SPONSOR:
        i = low.find(s)
        if i > 0:
            return n[:i]
    return n


def the_event(name: str) -> str:
    n = short_event(name)
    return n if n.lower().startswith("the ") else "the " + n


def initials(name: str) -> str:
    """The kit's QK.fmt.initials: first and last word's first letters ("Scottie Scheffler" -> "SS")."""
    p = "".join(c for c in str(name or "?") if c.isalnum() or c == " ").split()
    if not p:
        return "?"
    return (p[0][0] + p[-1][0] if len(p) > 1 else p[0][:3]).upper()


PARTICLES = ("de", "van", "von", "der", "den", "da", "di", "du", "le", "la", "del", "dos", "das", "ter")


def surname(name: str) -> str:
    """The last name for the climb's end labels: "De Roey", "van Rooyen", "Scheffler" (suffixes dropped)."""
    p = [w for w in str(name or "").split() if w.rstrip(".").lower() not in ("jr", "sr", "ii", "iii", "iv")]
    if not p:
        return str(name or "")
    i = len(p) - 1
    while i > 1 and p[i - 1].lower() in PARTICLES:
        i -= 1
    return " ".join(p[i:])


def finish(pos, tie, st) -> str:
    if st == "finish" and pos is not None:
        return ("T" if tie else "") + str(pos)
    return {"cut": "MC", "wd": "WD", "dq": "DQ", "mdf": "MDF", "dns": "DNS"}.get(str(st), str(st or "").upper())


def event_weeks(players: dict, today: date) -> list[date]:
    """Mondays of the weeks with at least one finished, rated event in the stream, up to today."""
    weeks = set()
    for p in players.values():
        for h in p.get("history") or []:
            d = _day(h[0]) if h else None
            if d and d <= today:
                weeks.add(_monday(d))
    return sorted(weeks)


def open_weeks(index: dict, tours: tuple, today: date) -> set[date]:
    """Weeks with one of the stream's events started and not final: they fold into now."""
    out = set()
    for e in (index or {}).get("week") or []:
        d = _day(e.get("start"))
        if e.get("tour") in tours and d and d <= today and e.get("status") != "final":
            out.add(_monday(d))
    return out


def rating_after(hist: list, boundary: date, now_rt):
    """The rating after every round before `boundary`: the entry of the first start on or after it (the rating
    carried into that event), else the rating now."""
    for h in hist:
        d = _day(h[0])
        if d and d >= boundary:
            return PW.num(h[1])
    return PW.num(now_rt)


def rankable(p: dict, row: dict, boundary: date, today: date, min_weight: float, active_days: int, half_life: float) -> bool:
    """rankings.json's rule as it stood on `boundary`: the rounds since then taken out of today's weight and count."""
    form = p.get("form") or []
    wt, n = PW.num(row.get("wt")), PW.num(row.get("n"))
    starts = [_day(h[0]) for h in (p.get("history") or []) if h]
    before = [d for d in starts if d and d < boundary]
    if not before:
        return False
    if (boundary - before[-1]).days > active_days:
        return False
    if not form or wt is None or n is None:
        return len(before) >= 6                     # no per-event rounds on file: about 20 rounds
    later_w, later_n = 0.0, 0
    for f in form:
        d = _day(f[0])
        k = int(PW.num(f[2]) or 0)
        if not d or d < boundary:
            continue
        later_n += k
        later_w += sum(0.5 ** (max(0, (today - (d + timedelta(days=i))).days) / half_life) for i in range(k))
    w_then = max(0.0, wt - later_w) * 2 ** ((today - boundary).days / half_life)
    return w_then >= min_weight and (n - later_n) >= MIN_ROUNDS


def snapshots(players: dict, rows: list, index: dict, tours: tuple, today: date, rk: dict, half_life: float):
    """[{key, label, date}] (oldest first, the last one now) and {pid: [rating at each snapshot]}."""
    shut = open_weeks(index, tours, today)
    weeks = [w for w in event_weeks(players, today) if w not in shut][-PW.MAX_SNAPSHOTS:]
    min_w, act = PW.num(rk.get("min_weight")) or 10.0, int(PW.num(rk.get("active_days")) or 400)
    snaps, paths = [], {r["pid"]: [] for r in rows}
    for w in weeks:
        b = w + timedelta(days=7)
        snaps.append({"key": "w" + w.isoformat(), "label": _label(w + timedelta(days=6)), "date": (w + timedelta(days=6)).isoformat()})
        for r in rows:
            p = players.get(r["pid"]) or {}
            ok = b > today or rankable(p, r, b, today, min_w, act, half_life)
            paths[r["pid"]].append(rating_after(p.get("history") or [], b, r.get("rt")) if ok else None)
    if not snaps:
        snaps.append({"key": "now", "label": "Now", "date": today.isoformat()})
        for r in rows:
            paths[r["pid"]].append(PW.num(r.get("rt")))
        return snaps, paths
    snaps[-1] = {"key": "now", "label": "Now", "date": today.isoformat()}
    for r in rows:
        paths[r["pid"]][-1] = PW.num(r.get("rt"))
    return snaps, paths


def phase_of(players: dict, index: dict, tours: tuple, today: date) -> str:
    """In season while one of the stream's events is under way, starts within a week or finished within three weeks;
    otherwise the off-season (the LPGA from the CME Group Tour Championship to January), and the page reads Final."""
    if open_weeks(index, tours, today):
        return "season"
    for e in (index or {}).get("week") or []:
        d = _day(e.get("start"))
        if e.get("tour") in tours and d and today - timedelta(days=21) <= d <= today + timedelta(days=7):
            return "season"
    weeks = event_weeks(players, today)
    return "season" if weeks and (today - weeks[-1]).days <= 21 else "offseason"


LOWER = ("No start", "Tied ", "Missed ", "Did not ")


def tidy(note: str | None) -> str | None:
    """note_for lowercases its own clause words after the first; do the same for this file's."""
    if not note:
        return note
    parts = note.split("; ")
    for i in range(1, len(parts)):
        if parts[i].startswith(LOWER):
            parts[i] = parts[i][0].lower() + parts[i][1:]
    return "; ".join(parts)


def _scout(sc: dict | None) -> dict:
    if not sc or not sc.get("cols"):
        return {}
    cols = sc["cols"]
    return {str(x[0]): dict(zip(cols, x)) for x in sc.get("rows") or []}


def week_chances(root: Path, index: dict, tours: tuple, today: date) -> dict:
    """{pid: (p, event name)}: this week's win chance for players in a field, live when the event has live chances,
    pre-event before it starts; an event under way without live chances gives none (a pre-event number would be stale)."""
    out = {}
    for e in (index or {}).get("week") or []:
        d = _day(e.get("start"))
        if e.get("tour") not in tours or not d or d > today + timedelta(days=6) or e.get("status") == "final":
            continue
        live = e.get("status") == "live"
        if live and e.get("key") != "lwin":
            continue
        ev = _read(root / "events" / f"{e.get('id')}.json") or {}
        for p in ev.get("players") or []:
            v = PW.num(p.get("lwin") if live else p.get("win"))
            if v is not None and p.get("pid"):
                out[str(p["pid"])] = (v, e.get("name") or ev.get("name"))
    return out


def _metric_tip(sc: dict | None, mid: str) -> str | None:
    for m in (sc or {}).get("metrics") or []:
        if m.get("id") == mid:
            return m.get("tip")
    return None


def groups(stream: str, board: dict, sc: dict | None, names: dict) -> dict | None:
    pool = [r for r in board.values() if r.get("q")]
    out = []
    for key, label, short, mid, mlabel, unit, stats in GROUPS[stream]:
        rows = []
        for r in pool:
            pid = str(r.get("id"))
            v = {mid: r.get(mid)}
            for s in stats:
                v[s[0]] = r.get(s[0])
            tour = r.get("tour")
            rows.append({"id": pid, "name": r.get("n") or names.get(pid) or pid, "team": TOUR_SHORT.get(tour, ""),
                         "colour": TOUR_COL.get(tour), "href": f"#/player/{pid}", "v": v})
        metric = {"key": mid, "label": mlabel, "unit": unit, "fmt": "+2", "dir": "higher", "tip": _metric_tip(sc, mid)}
        st = [{"key": s[0], "label": s[1], "fmt": s[2], "unit": s[3], "tip": _metric_tip(sc, s[0])} for s in stats]
        rule = "30+ rounds in two years" + ("; PGA Tour season statistics" if mid.startswith("c_") else "")
        g = PW.group(key, label, rows, metric, st, short=short, min_text=rule)
        if g:
            out.append(g)
    # golf has categories and splits, not positions: the page and Home take these words (power.js players.head, .cols)
    w = {"men": ("Players by strokes-gained category", "Best and worst in every category", "category"),
         "women": ("Players by part of the event and the round", "Best and worst in every split", "split")}.get(stream) or ("Players by category", "Best and worst in every category", "category")
    head = {"kicker": w[0], "title": w[1], "home": "by " + w[2], "chips": w[2].capitalize(),
            "sub": f"Every dot is a qualified player on the {w[2]}’s headline number, worse to the left, better to the right; the "
                   f"top three in their tour colour, the bottom three in coral. Tap a {w[2]} for its top five and bottom three."}
    return {"noun": "players", "head": head, "cols": {"team": "Tour"}, "groups": out} if out else None


def _extras(p: dict, row: dict, since: date | None, cat_rank: dict, chance) -> list[str]:
    """The site's own facts for the line on why: the best finish in the move's window (or a missed cut), a category
    the player leads, this week's chance; else when the player last teed it up."""
    out = []
    evs = [e for e in (p.get("events") or []) if _day(e.get("date"))]
    recent = [e for e in evs if since and _day(e["date"]) >= since]
    best = None
    for e in recent:
        if e.get("st") == "finish" and e.get("pos") is not None and (best is None or e["pos"] < best["pos"]):
            best = e
    if best and best["pos"] == 1:
        out.append("Won " + the_event(best.get("name")))
    elif best:
        out.append(("Tied " if best.get("tie") else "") + PW.ordinal(best["pos"]) + " at " + the_event(best.get("name")))
    elif recent:
        out.append(("Missed the cut at " if recent[0].get("st") == "cut" else "Did not finish ") + the_event(recent[0].get("name")))
    for lab, r in sorted(cat_rank.items(), key=lambda kv: kv[1])[:1]:
        if r <= 3:
            out.append(("No. 1" if r == 1 else PW.ordinal(r)) + f" in strokes gained {lab} (est.)")
    if chance and chance[0] >= 0.01 and (row.get("rank") or 99) <= 25:
        out.append(f"{PW.pct_text(chance[0])} to win {the_event(chance[1])} this week")
    if not recent and evs:
        e = evs[0]
        d = _day(e["date"])
        out.append(f"No start since {the_event(e.get('name'))} ({_label(d)})")
    return out


def league(root: Path, stream: str, rk: dict, index: dict, today: date, updated: str, half_life: float) -> dict | None:
    rows = [r for r in rk.get(stream) or [] if r.get("pid") and PW.num(r.get("rt")) is not None]
    if not rows:
        return None
    tours = STREAMS[stream]
    players = {}
    for r in rows:
        p = _read(root / "players" / f"{r['pid']}.json")
        if p:
            players[r["pid"]] = p
    snaps, paths = snapshots(players, rows, index, tours, today, rk, half_life)
    sc = _read(root / "scout" / f"{stream}.json")
    board = _scout(sc)
    names = {r["pid"]: r.get("name") for r in rows}
    # categories each player leads among the qualified (men)
    cat_rank: dict = {}
    if stream == "men":
        for mid, lab in (("c_ott", "off the tee"), ("c_app", "approach"), ("c_arg", "around the green"), ("c_putt", "putting")):
            q = sorted((x for x in board.values() if x.get("q") and PW.num(x.get(mid)) is not None), key=lambda x: -x[mid])
            for i, x in enumerate(q[:3]):
                cat_rank.setdefault(str(x["id"]), {})[lab] = i + 1
    chances = week_chances(root, index, tours, today)
    # the move's window: from the start of the last completed week (now stands in for it) to today
    since = date.fromisoformat(snaps[-2]["date"]) + timedelta(days=1) if len(snaps) >= 2 else None
    ents, extras = [], {}
    for r in rows:
        pid = r["pid"]
        p = players.get(pid) or {}
        starts, wins, top10 = int(r.get("starts") or 0), int(r.get("wins") or 0), int(r.get("top10") or 0)
        last5 = " ".join(finish(x[1], x[2], x[3]) for x in (r.get("l5") or [])[-5:] if len(x) >= 4)
        tour = r.get("tour")
        ent = {"id": pid, "name": r.get("name") or pid, "short": surname(r.get("name")), "abbr": initials(r.get("name")),
               "href": f"#/player/{pid}", "group": TOUR_SHORT.get(tour) if stream == "men" else (r.get("cc") or None),
               "rpath": paths.get(pid),
               "record": (f"{wins} win{'s' if wins != 1 else ''} in {starts} start{'s' if starts != 1 else ''}") if starts else None}
        stats = []
        if starts:
            stats.append({"label": "Top 10s", "text": f"{top10} of {starts}"})
        if last5:
            stats.append({"label": "Last five", "text": last5})
        if stats:
            ent["stats"] = stats
        ents.append(ent)
        extras[pid] = _extras(p, r, since, cat_rank.get(pid, {}), chances.get(pid))
    teams = PW.teams_block(ents, snaps, step="week", rating_fmt="+2", extra_notes=extras)[:TOP]
    phase = phase_of(players, index, tours, today)
    for i, t in enumerate(teams):
        t["colour"] = PALETTE[i % len(PALETTE)]
        t["note"] = tidy(t.get("note"))
        c = chances.get(t["id"])
        if c and phase == "season":
            t["chance"] = {"label": "Win this week", "p": round(c[0], 4)}
    season = today.year
    return PW.document(
        site=SITE, sport=SPORT, league=stream, label=LABEL[stream], season=season, season_label=f"{season} season",
        updated_at=updated, asof=today.isoformat(), phase=phase,
        rating={"label": "Our rating", "short": "Rating", "unit": f"strokes a round v {CENTRE[stream]}", "fmt": "+2",
                "tip": f"Strokes a round better than {CENTRE[stream]}, from every round against the field that played it, "
                       f"the recent ones counting most (a half-life of {int(half_life)} days): the number our forecasts use."},
        snapshots=snaps, teams=teams, step="week", kind="players", noun="players", parts=None,
        players=groups(stream, board, sc, names),
        notes=["Each week's ranking is the one after that week's finished events; Now adds any finished since. A player "
               "without a start since keeps the same rating and moves only when others pass.",
               "The top 100 of the ranking (the ranking's own rule: enough recent rounds behind the rating). Colours only tell the lines apart.",
               "Groups: " + ("our strokes-gained categories, estimated from PGA Tour season statistics, for the regulars (30+ rounds in two years) who have them."
                             if stream == "men" else "strokes gained by part of the event and of the round, for the regulars (30+ rounds in two years); the LPGA publishes no season statistics for our categories.")])


def build(data_root: Path, now: str | None = None) -> dict | None:
    root = Path(data_root)
    rk = _read(root / "rankings.json") or {}
    ix = _read(root / "index.json") or {}
    if not rk:
        return None
    mj = _read(root / "model.json") or {}
    half_life = PW.num((mj.get("params") or {}).get("half_life")) or HALF_LIFE
    today = _day(ix.get("today")) or _day(rk.get("updated_at")) or date.today()
    updated = now or ix.get("updated_at") or rk.get("updated_at") or _now()
    docs = [league(root, s, rk, ix, today, updated, half_life) for s in STREAMS]
    return PW.write(root, [d for d in docs if d], site=SITE, sport=SPORT, updated_at=updated, default="men")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "docs" / "green" / "data"
    print(build(r))
