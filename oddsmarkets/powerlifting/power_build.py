"""The Quant Iron's power rankings: data/power/men_raw.json and women_raw.json (the default men_raw) and the site index
data/power.json (the shape is oddsmarkets/common/power.py; the kit's power.js draws them on #/power and on Home).
Every stream is its own DOTS scale (sex x raw, wraps, equipped), so streams are never ranked together. Wraps and
equipped are built the same way (BUILT below) but not listed yet: Home's league picker is one row of buttons that
six streams overflow on a phone (375 px), so they wait for it to wrap or scroll.

Read from the payloads this build has just written (no new fetching, no new model):

    rankings.json         our rating now (expected DOTS at the next meet) per stream, rank, IPF class, bodyweight,
                          meets, best DOTS in 12 months, form against our forecast, the 90-day move (mv, d90)
    rank_paths.json       today's top 100 per stream: rank and rating on the first day of each of the last ten months
                          (pages.py _rank_paths: the site's own rating on that day, ranked by the rankings' rule)
    players/<pid>.json    the meet log (lifts, totals, DOTS, our pre-meet expectation, PRs) for the notes and parts
    scout/<stream>.json   the two-year lifts (best squat, bench, deadlift, total) and bodyweight for the class groups
    build.json            the build time

    build(data_root, now=None) -> {"n", "bytes", "max", "leagues"}  (python -m oddsmarkets.powerlifting.power_build <data>)

Snapshots: monthly (meets are sparse), the first day of each of the last ten months up to the archive's last meet
day, the last one replaced by now. A rating on a date uses only meets dated before it: a meet counts from the next
day (checked on the 14 Nov 2026 payloads: the pre-meet expectation of 440 of 453 men's raw meets in 2026 by today's
top 300 is the rating rebuilt from the meets strictly before the meet day, 3 with that day's meet included). So the
snapshot "Sep" is the ranking on 1 October, every September meet in, and the month still being filled (the archive
lags by weeks and publishes weekly) folds into now: the move reads against the last month before. The archive
back-fills, so a month's snapshot is "the meets held before that day, as the archive has them now". The rating moves
with time too (the forecast knows how long since the last meet and the lifter's age), so a lifter can move without
lifting. Without rank_paths.json (a build before it existed) the snapshots are 90 days ago (rankings.json's exact
mv and d90) and now.

Groups: the IPF weight classes of the stream's sex (rankings.json's class order), every ranked lifter in the class on
our rating, with the best squat, bench, deadlift and total of the last two years and the bodyweight.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import power as PW

log = logging.getLogger(__name__)

SITE, SPORT = "iron", "powerlifting"
BUILT = ("men_raw", "women_raw")      # the streams listed; any key of STREAMS works
STREAMS = {"men_raw": "Men · Raw", "women_raw": "Women · Raw", "men_wraps": "Men · Wraps", "women_wraps": "Women · Wraps",
           "men_eq": "Men · Equipped", "women_eq": "Women · Equipped"}
DEFAULT = "men_raw"
TOP = 100
PALETTE = ["#7d93ff", "#ff6a4d", "#5ec8f0", "#c39be8", "#8fd16a", "#f28fb5", "#d9b38c", "#ffb84d", "#3fd4b4", "#b0bccf"]
ACCENT = "#e6a06e"          # the kit's powerlifting accent (tokens.css --a-powerlifting): the class tables' marks
PARTS = [{"key": "s", "label": "Squat"}, {"key": "b", "label": "Bench"}, {"key": "d", "label": "Deadlift"}]
STATS = [("squat", "Squat", "1", "kg"), ("bench", "Bench", "1", "kg"), ("dead", "Deadlift", "1", "kg"),
         ("total", "Total", "1", "kg"), ("bw", "Bodyweight", "1", "kg")]


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


def _ts(s) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _bare(name: str) -> str:
    """The name without OpenPowerlifting's "#N" same-name suffix ("Chris Kennedy #1" -> "Chris Kennedy")."""
    p = str(name or "").split()
    while p and p[-1].startswith("#") and p[-1][1:].isdigit():
        p = p[:-1]
    return " ".join(p) or str(name or "")


def initials(name: str) -> str:
    p = "".join(c for c in _bare(name) if c.isalnum() or c == " ").split()
    if not p:
        return "?"
    return (p[0][0] + p[-1][0] if len(p) > 1 else p[0][:3]).upper()


PARTICLES = ("de", "van", "von", "der", "den", "da", "di", "du", "le", "la", "del", "dos", "das", "ter")


def surname(name: str) -> str:
    p = [w for w in _bare(name).split() if w.rstrip(".").lower() not in ("jr", "sr", "ii", "iii", "iv")]
    if not p:
        return _bare(name)
    i = len(p) - 1
    while i > 1 and p[i - 1].lower() in PARTICLES:
        i -= 1
    return " ".join(p[i:])


def cc3(cc) -> str:
    """The site's country mark (ov.js, core.js followItem): the first three letters, capitals."""
    return str(cc or "")[:3].upper()


def kg(v) -> str:
    v = PW.num(v)
    if v is None:
        return ""
    return (f"{v:,.1f}" if v % 1 else f"{v:,.0f}") + " kg"


def snapshots(rows: list, paths: dict | None, today: date):
    """[{key, label, date}], {pid: [rank ...]} and {pid: [rating ...]} aligned, the last one now."""
    if paths and paths.get("dates"):
        dates = [_day(x) for x in paths["dates"]]
        snaps = []
        for d in dates:
            m = d - timedelta(days=1)
            lab = m.strftime("%b") + ("" if m.year == today.year else " " + m.strftime("%y"))
            snaps.append({"key": "m" + d.isoformat(), "label": lab, "date": d.isoformat()})
        snaps[-1] = {"key": "now", "label": "Now", "date": today.isoformat()}
        ranks, rts = {}, {}
        for r in rows:
            p = paths.get("pid_paths", {}).get(r["pid"]) or [[None, None]] * len(dates)
            ranks[r["pid"]] = [x[0] for x in p[:-1]] + [r.get("rank")]
            rts[r["pid"]] = [x[1] for x in p[:-1]] + [PW.num(r.get("rt"))]
        return snaps, ranks, rts, "month"
    # fallback: rankings.json's exact 90-day rank and rating, then now
    d90 = today - timedelta(days=90)
    snaps = [{"key": "d90", "label": f"{d90.day} {d90.strftime('%b')}", "date": d90.isoformat()},
             {"key": "now", "label": "Now", "date": today.isoformat()}]
    ranks, rts = {}, {}
    for r in rows:
        mv, d = r.get("mv"), PW.num(r.get("d90"))
        rt = PW.num(r.get("rt"))
        ranks[r["pid"]] = [r["rank"] + mv if isinstance(mv, int) else None, r.get("rank")]
        rts[r["pid"]] = [rt - d if (rt is not None and d is not None) else None, rt]
    return snaps, ranks, rts, "quarter"


def _parts(p: dict, stream: str, rt, today: date) -> dict | None:
    """The rating split by each lift's share of the best total in the last 12 months (else the latest meet with all
    three lifts): the overview power board's split (pages.py _index)."""
    rt = PW.num(rt)
    logs = [x for x in (p or {}).get("log") or [] if x.get("st") == stream and PW.num(x.get("tot"))
            and all(PW.num(x.get(k)) for k in ("sq", "bp", "dl"))]
    if rt is None or not logs:
        return None
    yr = [x for x in logs if _day(x.get("date")) and _day(x["date"]) > today - timedelta(days=365)]
    b = max(yr, key=lambda x: x["tot"]) if yr else logs[-1]
    tot = b["sq"] + b["bp"] + b["dl"]
    return {"s": rt * b["sq"] / tot, "b": rt * b["bp"] / tot, "d": rt * b["dl"] / tot} if tot else None


def _meet_words(x: dict, today: date) -> str:
    d = _day(x.get("date"))
    when = f" ({d.day} {d.strftime('%b')}{'' if d.year == today.year else ' ' + str(d.year)})" if d else ""
    return (x.get("mn") or "a meet") + when


def _extras(p: dict, stream: str, since: date | None, cls_one: bool, cls: str, today: date) -> list[str]:
    """The lifter's own story in the move's window from the meet log: a PR, against our forecast; the class lead;
    else the last meet."""
    out = []
    logs = [x for x in (p or {}).get("log") or [] if x.get("st") == stream and _day(x.get("date"))]
    recent = [x for x in logs if since and _day(x["date"]) >= since and x.get("tot") is not None]
    if recent:
        x = recent[-1]
        if x.get("pr"):
            out.append(f"Lifetime best total, {kg(x['tot'])}, at {_meet_words(x, today)}")
        e, dots = PW.num(x.get("exp")), PW.num(x.get("dots"))
        if e is not None and dots is not None and abs(dots - e) >= 0.5:
            out.append(("Beat our forecast by " if dots > e else "Fell short of our forecast by ") + f"{abs(dots - e):.1f} DOTS at {_meet_words(x, today)}")
        elif not x.get("pr"):
            out.append(f"Totalled {kg(x['tot'])} at {_meet_words(x, today)}")
    if cls_one and cls:
        out.append(f"Top of the {cls} kg class")
    if not recent and logs:
        x = [y for y in logs if y.get("tot") is not None][-1:] or logs[-1:]
        out.append(f"No meet since {_meet_words(x[0], today)}")
    return out


LOWER = ("No meet", "Lifetime ", "Beat ", "Fell ", "Totalled ", "Top of ")


def tidy(note: str | None) -> str | None:
    if not note:
        return note
    parts = note.split("; ")
    for i in range(1, len(parts)):
        if parts[i].startswith(LOWER):
            parts[i] = parts[i][0].lower() + parts[i][1:]
    return "; ".join(parts)


def _lifts(p: dict, stream: str, today: date) -> dict:
    """Best squat, bench, deadlift and total of the last two years from a lifter's meet log (the Scouting Room's
    window), for a ranked lifter the two-year pool leaves out (it needs two meets in the window)."""
    out = {}
    for x in (p or {}).get("log") or []:
        d = _day(x.get("date"))
        if x.get("st") != stream or not d or d <= today - timedelta(days=730):
            continue
        for k, c in (("squat", "sq"), ("bench", "bp"), ("dead", "dl"), ("total", "tot")):
            v = PW.num(x.get(c))
            if v is not None and v > 0:
                out[k] = max(out.get(k, 0.0), v)
    return out


RANK_CAP = 3000      # pages.RANK_CAP: rankings.json lists at most this many lifters per stream


def pool_rule(n: int) -> str:
    """The qualifying rule, and the cap when rankings.json is cut at it (the bottom of a class is then the bottom of
    the listed lifters, not of every ranked one)."""
    rule = "3+ scored meets, one in the last 400 days"
    return f"in our top {RANK_CAP:,}: {rule}" if n >= RANK_CAP else rule


def groups(root: Path, stream: str, rows_all: list, classes: list, scout: dict | None, today: date) -> dict | None:
    sc = {}
    if scout and scout.get("cols"):
        cols = scout["cols"]
        sc = {str(x[0]): dict(zip(cols, x)) for x in scout.get("rows") or []}
    out = []
    for c in classes:
        rows = []
        for r in rows_all:
            if str(r.get("cls")) != str(c):
                continue
            s = sc.get(r["pid"])
            if s is None and r.get("pg"):
                s = _lifts(_read(root / "players" / f"{r['pid']}.json"), stream, today)
            s = s or {}
            v = {"rt": r.get("rt")}
            for k, *_ in STATS:
                v[k] = s.get(k) if k != "bw" else (r.get("bw") if r.get("bw") is not None else s.get("bw"))
            rows.append({"id": r["pid"], "name": r.get("name") or r["pid"], "team": cc3(r.get("cc")), "colour": ACCENT,
                         "href": f"#/player/{r['pid']}" if r.get("pg") else None, "v": v})
        key = str(c).replace("+", "p")
        g = PW.group(key, f"{c} kg", rows,
                     {"key": "rt", "label": "DOTS expected", "fmt": "1", "dir": "higher",
                      "tip": "Our rating: the DOTS we expect at the lifter's next full-power meet."},
                     [{"key": k, "label": lab, "fmt": f, "unit": u} for k, lab, f, u in STATS], short=str(c),
                     min_text=pool_rule(len(rows_all)) + "; lifts are the best of the last two years")
        if g:
            out.append(g)
    # powerlifting has weight classes, not positions: the page and Home take these words (power.js players.head, .cols)
    head = {"kicker": "Lifters by weight class", "title": "Best and worst in every class", "home": "by weight class", "chips": "Weight class",
            "sub": "Every dot is a ranked lifter in the class on our rating, worse to the left, better to the right; the top three "
                   "highlighted, the bottom three in coral. Tap a class for its top five and bottom three."}
    return {"noun": "lifters", "head": head, "cols": {"player": "Lifter", "team": "Country"}, "groups": out} if out else None


def league(root: Path, stream: str, rk: dict, paths_all: dict | None, today: date, updated: str) -> dict | None:
    rows_all = [r for r in ((rk.get("streams") or {}).get(stream) or {}).get("rows") or [] if r.get("pid") and PW.num(r.get("rt")) is not None]
    if not rows_all:
        return None
    rows = rows_all[:TOP]
    sp = None
    if paths_all:
        pp = (paths_all.get("streams") or {}).get(stream)
        if pp:
            sp = {"dates": paths_all["dates"], "pid_paths": pp}
    snaps, ranks, rts, step = snapshots(rows, sp, today)
    since = _day(snaps[-2]["date"]) if len(snaps) >= 2 else None      # the move's window: meets from that day on
    cls_first = {}
    for r in rows_all:
        cls_first.setdefault(str(r.get("cls")), r["pid"])
    ents, extras, players = [], {}, {}
    for r in rows:
        pid = r["pid"]
        p = _read(root / "players" / f"{pid}.json") or {}
        players[pid] = p
        stats = []
        b12 = PW.num(r.get("best12"))
        if b12 is not None:
            stats.append({"label": "Best DOTS, 12 months", "text": f"{b12:.1f}"})
        tots = [x for x in p.get("log") or [] if x.get("st") == stream and PW.num(x.get("tot")) and _day(x.get("date"))
                and _day(x["date"]) > today - timedelta(days=365)]
        if tots:
            stats.append({"label": "Best total, 12 months", "text": kg(max(x["tot"] for x in tots))})
        if PW.num(r.get("bw")) is not None:
            stats.append({"label": "Bodyweight", "text": kg(r["bw"])})
        n = int(r.get("n") or 0)
        ent = {"id": pid, "name": r.get("name") or pid, "short": surname(r.get("name")), "abbr": initials(r.get("name")),
               "href": f"#/player/{pid}" if r.get("pg") else None,
               "group": " · ".join(x for x in ((f"{r['cls']} kg" if r.get("cls") else ""), r.get("cc") or "") if x) or None,
               "record": f"{n} meet{'s' if n != 1 else ''}" if n else None, "rpath": rts[pid], "parts": _parts(p, stream, r.get("rt"), today)}
        if stats:
            ent["stats"] = stats[:3]
        ents.append(ent)
        extras[pid] = _extras(p, stream, since, cls_first.get(str(r.get("cls"))) == pid, str(r.get("cls") or ""), today)
    teams = PW.teams_block(ents, snaps, step=step, rating_fmt="1", extra_notes=extras)
    # the true ranks: today's from rankings.json, the past ones from rank_paths.json (every lifter ranked that day),
    # not the order among these hundred
    order = {r["pid"]: i for i, r in enumerate(rows)}
    rank_now = {r["pid"]: r["rank"] for r in rows}
    for t in teams:
        t["rank"] = rank_now[t["id"]]
        t["path"] = ranks[t["id"]]
        t["prev"] = t["path"][-2] if len(t["path"]) >= 2 else None
        t["move"] = (t["prev"] - t["rank"]) if t["prev"] is not None else None
        t["note"] = tidy(PW.note_for(t, len(rows_all), [], {}, step, extras.get(t["id"])))
    teams.sort(key=lambda t: (t["rank"], order[t["id"]]))
    form = {r["pid"]: r.get("form") for r in rows}
    for i, t in enumerate(teams):
        t["colour"] = PALETTE[i % len(PALETTE)]
        if form.get(t["id"]):
            t["form"] = form[t["id"]]               # after the notes: W here is "beat our forecast", not a win
    sex = "F" if stream.startswith("women") else "M"
    classes = ((rk.get("classes") or {}).get(sex)) or []
    unit = rk.get("unit") or "DOTS"
    return PW.document(
        site=SITE, sport=SPORT, league=stream, label=STREAMS[stream], season=today.year, season_label=f"{today.year}",
        updated_at=updated, asof=today.isoformat(), phase="season",
        rating={"label": "Our rating", "short": "DOTS", "unit": f"{unit} expected at the next meet", "fmt": "1",
                "tip": "The DOTS we expect at a lifter's next full-power meet (DOTS puts every bodyweight on one scale), "
                       "from the last meet, the best, the longer-run level, meets so far, age and time since the last meet."},
        snapshots=snaps, teams=teams, step=step, kind="players", noun="lifters", parts=PARTS,
        players=groups(root, stream, rows_all, classes, _read(root / "scout" / f"{stream}.json"), today),
        notes=["Each month's ranking is the one on the first day of the next month, from the meets held before it as the "
               "archive has them now (it fills in for weeks); Now adds every meet since. Our rating also moves with time "
               "since the last meet, so a lifter can move without lifting." if step == "month" else
               "The first snapshot is our ranking 90 days ago, rebuilt from the meets before that day; Now adds every meet since.",
               (f"The top {TOP} of our ranking (3+ scored meets, one in the last 400 days; the ranking file lists the top {RANK_CAP:,}). "
                if len(rows_all) >= RANK_CAP else f"The top {TOP} of {len(rows_all):,} ranked lifters (3+ scored meets, one in the last 400 days). ") +
               "The bar splits the "
               "rating by each lift's share of the best total of the last 12 months. Form: the last five meets against our "
               "pre-meet forecast (W beat it, L fell short). Colours only tell the lines apart.",
               "Weight classes: the IPF classes at the lifter's latest bodyweight; lifts are the best of the last two years."])


def build(data_root: Path, now: str | None = None) -> dict | None:
    root = Path(data_root)
    rk = _read(root / "rankings.json") or {}
    if not rk.get("streams"):
        return None
    bj = _read(root / "build.json") or {}
    updated = now or bj.get("updated_at") or rk.get("updated_at") or _now()
    today = _day(bj.get("today")) or _day(rk.get("updated_at")) or date.today()
    paths = _read(root / "rank_paths.json")
    # the paths must come from the same build as the rankings (a failed step leaves yesterday's file behind)
    t1, t2 = _ts((paths or {}).get("updated_at")), _ts(rk.get("updated_at"))
    if not paths or not t1 or not t2 or abs((t1 - t2).total_seconds()) > 6 * 3600:
        if paths:
            log.warning("rank_paths.json is not from this build: the power rankings fall back to 90 days ago")
        paths = None
    docs = [league(root, s, rk, paths, today, updated) for s in BUILT]
    return PW.write(root, [d for d in docs if d], site=SITE, sport=SPORT, updated_at=updated, default=DEFAULT)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "docs" / "iron" / "data"
    print(build(r))
