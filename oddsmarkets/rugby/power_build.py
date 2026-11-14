"""The Quant Scrum's power rankings: data/power/men.json and data/power/women.json (one file per scope) and the site
index data/power.json (the shape is oddsmarkets/common/power.py; the kit's power.js draws them on #/<S>/power and on
Home). The default is men.

Read from the payloads the build has just written (no new fetching, no new model):

    index.json              the sides of each scope (name, abbreviation, colours, tier), the build time
    <S>/ratings.json        our rating now and its monthly history (hist: [[YYYY-MM, rating after the month's last
                            test]]), the rank (only sides tied to the main pool are ranked: the site's rule), form, the
                            record over 12 months, the World Rugby points and rank, the 12-month change
    <S>/comps/nc.json       the Nations Championship simulation (each side's title chance while it is being played)
    <S>/comps/rwc.json      the next World Cup's simulation (each side's title chance)
    <S>/players.json        the Scouting Room's board: every player's shrunk per-80 rates over the last two years,
                            position group, minutes, the qualified flag and the last test

    build(data_root, now=None) -> {"n", "bytes", "max", "leagues"}     (python -m oddsmarkets.rugby.power_build)

Snapshots, no look-ahead: a hist entry is the rating AFTER the side's last test of that month (build.walk appends the
rating after each test's update and pages.monthly keeps the month's last value; checked on the 14 Nov 2026 payloads:
South Africa lost 19-21 in Paris on 13 Nov, their last test, and their 2026-11 entry, 29.97, is the current rating,
which counts that test; France, the winners, read 23.95 in both). A snapshot is a month end; each side has its last
entry dated in or before that month, so only tests played by then count. Tests are sparse, so the step is a calendar
month (a week would leave most steps empty; a test window has no fixed edges): the last ten months back from the
latest month with a test, which folds into Now (the current rating), so the move reads against the month before, as a
weekly ranking does while a week is played. A month without tests is a flat step, so "No. 1 for 6 months" counts real
months. One caveat: the model pulls every side a tenth of the way back toward its tier's level at each new year,
applied at the year's first test, which a month-end value of a side yet to play that year does not show.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import power as PW

log = logging.getLogger(__name__)

SITE, SPORT = "scrum", "rugby"
SCOPES = ("men", "women")
DEFAULT = "men"
LABEL = {"men": "Men's tests", "women": "Women's tests"}
RECENT_DAYS = 400            # the overview's "players to watch" rule: a test in the last 13 months or so
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# position groups (the site's: oddsmarkets/rugby/players.py GROUP_ORDER) and the numbers a fan reads for each, all
# per 80 minutes unless said: (key, label, fmt, tip)
STATS = {
    "front_row": [("tk", "Tackles/80", "1", None), ("car", "Carries/80", "1", None), ("tkpct", "Tackle %", "pct0", "Tackles made of those attempted"),
                  ("pc", "Pens/80", "1", "Penalties conceded per 80 minutes"), ("gp", "Tests", "0", "Tests played in the window")],
    "lock": [("tk", "Tackles/80", "1", None), ("car", "Carries/80", "1", None), ("m", "Metres/80", "0", None),
             ("tkpct", "Tackle %", "pct0", "Tackles made of those attempted"), ("gp", "Tests", "0", "Tests played in the window")],
    "back_row": [("car", "Carries/80", "1", None), ("m", "Metres/80", "0", None), ("tk", "Tackles/80", "1", None),
                 ("db", "Beaten/80", "1", "Defenders beaten per 80 minutes"), ("gp", "Tests", "0", "Tests played in the window")],
    "halves": [("pts", "Points/80", "1", None), ("ta", "Try ast/80", "2", "Try assists per 80 minutes"), ("kfh", "Kicks/80", "1", "Kicks from hand per 80 minutes"),
               ("kpct", "Goal kicks %", "pct0", "Goal-kicking success"), ("gp", "Tests", "0", "Tests played in the window")],
    "centres": [("m", "Metres/80", "0", None), ("cb", "Breaks/80", "2", "Clean breaks per 80 minutes"), ("db", "Beaten/80", "1", "Defenders beaten per 80 minutes"),
                ("tries", "Tries/80", "2", None), ("gp", "Tests", "0", "Tests played in the window")],
    "back_three": [("tries", "Tries/80", "2", None), ("m", "Metres/80", "0", None), ("cb", "Breaks/80", "2", "Clean breaks per 80 minutes"),
                   ("db", "Beaten/80", "1", "Defenders beaten per 80 minutes"), ("gp", "Tests", "0", "Tests played in the window")],
}
POS = {"P": "Prop", "H": "Hooker", "FL": "Flanker", "N8": "No. 8", "SH": "Scrum-half", "FH": "Fly-half", "W": "Wing", "FB": "Full-back"}
MIXED = {"front_row", "back_row", "halves", "back_three"}     # groups of two positions: each row says which
ORDER = ["front_row", "lock", "back_row", "halves", "centres", "back_three"]
NAMES = {"front_row": "Front row", "lock": "Locks", "back_row": "Back row", "halves": "Half-backs", "centres": "Centres", "back_three": "Back three"}
METRIC = {"key": "val80", "label": "Scrum value/80", "unit": "points per 80 minutes", "fmt": "+2", "dir": "higher",
          "tip": "Our Scrum value: the points a player adds per 80 minutes over a replacement-level player at the position, "
                 "from the process numbers that move the margin (metres, breaks, defenders beaten, offloads, tackles, "
                 "missed tackles, turnovers, penalties, cards) plus goal kicking above an average kicker."}


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _month_end(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def snapshots(teams: list[dict]) -> tuple[list[dict], dict]:
    """[{key, label, date}] (oldest first, the last one "Now") and {id: [rating at each snapshot]} for the ranked sides:
    the ends of the calendar months back from the latest month with a test among them, which is Now (a month with no
    test is a flat step: nothing moved)."""
    hist = {t["id"]: sorted((str(h[0])[:7], PW.num(h[1])) for h in t.get("hist") or [] if h and len(h) > 1 and PW.num(h[1]) is not None)
            for t in teams}
    tested = {mm for h in hist.values() for mm, _v in h}
    if not tested:
        return [], {}
    last = max(tested)
    y, m = int(last[:4]), int(last[5:7])
    months = []
    for _ in range(PW.MAX_SNAPSHOTS):                 # consecutive calendar months back from the latest with a test
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    months = sorted(mm for mm in months if mm >= min(tested))

    def at(h, m):
        v = None
        for mm, x in h:
            if mm > m:
                break
            v = x
        return v
    paths = {}
    for t in teams:
        p = [at(hist[t["id"]], m) for m in months]
        p[-1] = PW.num(t.get("rating"))
        paths[t["id"]] = p
    snaps = [{"key": m, "label": f"{MONTHS[int(m[5:7]) - 1]} {m[:4]}", "date": _month_end(m)} for m in months]
    snaps[-1] = {"key": "now", "label": "Now", "date": None}
    return snaps, paths


def _chances(data: Path, S: str, asof: str) -> tuple[dict, dict]:
    """{name: p} for the Nations Championship title while it is being played, and for the next World Cup's title."""
    nc, rwc = {}, {}
    d = _read(data / S / "comps" / "nc.json") or {}
    live = bool(d.get("fixtures")) or any(str(f.get("date") or "")[:10] >= asof for f in d.get("finals") or [])
    if live:
        for r in ((d.get("sim") or {}).get("teams") or []):
            if r.get("team") and PW.num(r.get("champion")) is not None:
                nc[r["team"]] = PW.num(r["champion"])
    w = _read(data / S / "comps" / "rwc.json") or {}
    for r in ((w.get("sim") or {}).get("teams") or []):
        if r.get("team") and PW.num(r.get("champion")) is not None:
            rwc[r["team"]] = PW.num(r["champion"])
    return nc, rwc


def _players(data: Path, S: str, info: dict) -> tuple[dict | None, str | None]:
    pj = _read(data / S / "players.json") or {}
    cols = pj.get("cols") or []
    rows = [dict(zip(cols, r)) for r in pj.get("rows") or []]
    if not rows:
        return None, None
    latest = max((str(r.get("last") or "") for r in rows), default="")
    cut = (date.fromisoformat(latest[:10]) - timedelta(days=RECENT_DAYS)).isoformat() if latest else ""
    q_min = PW.num(pj.get("min_q")) or 160
    since = str(pj.get("from") or "")
    labels = {g.get("id"): g.get("label") for g in pj.get("groups") or [] if g.get("id")}
    groups = []
    for key in ORDER:
        pool = []
        for r in rows:
            if r.get("grp") != key or not r.get("q") or str(r.get("last") or "") < cut:
                continue
            tid = str(r.get("team") or "")
            t = info.get(tid) or {}
            pool.append({"id": str(r.get("id")), "name": r.get("n"), "team": t.get("abbr") or tid, "colour": t.get("colour"),
                         "href": f"#/{S}/player/{r.get('id')}", "sub": POS.get(r.get("pos")) if key in MIXED else None, "v": r})
        st = [{"key": k, "label": lab, "fmt": f, "tip": tip} for k, lab, f, tip in STATS[key]]
        label = labels.get(key) or NAMES[key]
        g = PW.group(key, label, pool, METRIC, st, short=label,
                     min_text=f"{int(q_min)}+ minutes in tests since {_pretty(since)}, the latest test after {_pretty(cut)}")
        if g:
            groups.append(g)
    return ({"noun": "players", "groups": groups} if groups else None), latest


def _pretty(iso: str) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def scope_doc(data: Path, S: str, idx: dict, now: str | None = None) -> dict | None:
    info = (((idx.get("scopes") or {}).get(S) or {}).get("teams")) or {}
    rj = _read(data / S / "ratings.json") or {}
    ranked = [t for t in rj.get("teams") or [] if t.get("rank") and t.get("id") is not None]
    for t in ranked:
        t["id"] = str(t["id"])
    snaps, paths = snapshots(ranked)
    if not snaps:
        return None
    asof = str(rj.get("asof") or (now or _now())[:10])
    nc, rwc = _chances(data, S, asof)
    ents, extra = [], {}
    for t in ranked:
        i = info.get(t["id"]) or {}
        name = i.get("name") or t["id"]
        rec = t.get("rec12") or []
        ent = {"id": t["id"], "name": name, "short": name[:-6] if name.endswith(" Women") else None, "abbr": i.get("abbr"), "colour": i.get("colour"), "href": f"#/{S}/team/{t['id']}",
               "group": f"Tier {t['tier']}" if t.get("tier") else None, "rpath": paths.get(t["id"]),
               "record": f"W{rec[0]} D{rec[1]} L{rec[2]}" if len(rec) == 3 and sum(rec) else None,
               "form": t.get("form") or None}
        if name in nc and nc[name] >= 0.0005:
            ent["chance"] = {"label": "Nations Championship", "p": round(nc[name], 4)}
        cells = []
        if t.get("wr_rank") and PW.num(t.get("wr")) is not None:
            cells.append({"label": "World Rugby", "text": f"{PW.ordinal(t['wr_rank'])}, {float(t['wr']):.2f} pts"})
        if name in rwc and rwc[name] >= 0.0005:
            cells.append({"label": "World Cup 2027", "text": PW.pct_text(rwc[name])})
        if PW.num(t.get("d365")) is not None:
            d = float(t["d365"])
            cells.append({"label": "12-month change", "text": ("+" if d > 0 else "−" if d < 0 else "±") + f"{abs(d):.1f} pts"})
        if cells:
            ent["stats"] = cells[:3]
        if t.get("wr_rank") and abs(int(t["wr_rank"]) - int(t["rank"])) >= 3:
            extra[t["id"]] = [f"{PW.ordinal(t['wr_rank'])} in the World Rugby rankings"]
        ents.append(ent)
    rows = PW.teams_block(ents, snaps, step="month", rating_fmt="+1", extra_notes=extra)
    players, latest = _players(data, S, info)
    year = int(asof[:4]) if asof[:4].isdigit() else None
    notes = ["Ranked on our rating, the points margin we expect against an average test side on a neutral ground, from "
             "every result. Each snapshot is the rating at a month's end, counting the tests played by then (a month "
             "without tests changes nothing); Now adds every test since the last one. A side's record is its last 12 months.",
             f"Only the {len(rows)} sides tied to the main pool are ranked, the site's rule: five or more rated tests, and "
             "tier one or two or three tests against such sides in four years."]
    if players:
        notes.append("Players: Scrum value per 80 minutes and the per-80 numbers, shrunk toward the position for small "
                     "samples, over the tests with player statistics in the last two years" +
                     (f" (for women's tests, the latest are from {_pretty(latest)})" if S == "women" and latest else "") +
                     "; qualified as the rule under each group says.")
    return PW.document(site=SITE, sport=SPORT, league=S, label=LABEL.get(S, S), season=year, season_label=str(year or ""),
                       updated_at=now or idx.get("updated_at") or _now(), asof=asof, phase="season",
                       rating={"label": "Our rating", "short": "Rating", "unit": "points a test against an average test side", "fmt": "+1",
                               "tip": "The margin we expect against an average test side on a neutral ground, from every result, "
                                      "with home ground, travel and rest taken out; each new year it drifts a tenth of the way "
                                      "back toward the side's tier."},
                       snapshots=snaps, teams=rows, step="month", kind="teams", noun="teams", players=players, notes=notes)


def build(data_root: Path, now: str | None = None) -> dict | None:
    data = Path(data_root)
    idx = _read(data / "index.json") or {}
    docs = []
    for S in SCOPES:
        if not ((idx.get("scopes") or {}).get(S) or {}).get("ok"):
            continue
        try:
            d = scope_doc(data, S, idx, now)
        except Exception as exc:  # noqa: BLE001  (one scope failing never takes the other down)
            log.error("power rankings: %s skipped: %r", S, exc)
            continue
        if d:
            docs.append(d)
    if not docs:
        return None
    return PW.write(data, docs, site=SITE, sport=SPORT, updated_at=now or idx.get("updated_at") or _now(), default=DEFAULT)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "docs" / "scrum" / "data"
    print(build(root))
