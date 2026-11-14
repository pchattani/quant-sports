"""The Ace's power rankings: data/power/atp.json, data/power/wta.json and the site index data/power.json (the shape is
oddsmarkets/common/power.py; the kit's power.js draws them on #/<T>/power).

Read from the payloads this build has just written, per tour T (no fetching, no new model):

    index.json              the tour's year, the events in play and the matches still to come
    <T>/elo.json            our Elo now ("current": overall and by surface, the rank), the history of the current top 100
                            ("history": {pid: [[date, overall Elo after the match, surface]]}, last five years) and the
                            Elo constants (the inactivity pull: idle_days, rho)
    <T>/players.json        the season's catalogue: names, countries, W-L, titles, `qualified` (the season's match floor),
                            the serve and return ratings, the surface blocks and `surface_floor`
    <T>/players_index.json  names for anyone the catalogue lacks
    <T>/rankings.json       the official ranking
    <T>/race.json           the season simulation (Finals chances), the events left, this week's results ("week")
    <T>/<year>/events.json  event names, levels and cities (for the week's results)

    build(data_root, now=None) -> {"n", "bytes", "max", "leagues"}     (python -m oddsmarkets.tennis.analytics.power_build)

The main ranking is the top 100 on our overall Elo (kind players), shown against the average of those 100 at each
snapshot so the list's bar runs either side of zero; the Elo itself is a stat beside it.

Snapshots, no look-ahead: a history row [date, elo] is the rating after that match (checked on the 2026 payloads:
Basilashvili won his Almaty semi-final on 24 Oct and his entry rose from 1622.0 to 1635.3, then lost the final on
25 Oct and it fell to 1630.6). A snapshot is the end of a week of play (Sunday): each player's last row on or before it,
with the site's own inactivity pull applied to the next day exactly as elo.ratings_at does for "current" (R <- 1500 +
(R - 1500) * rho ** ((gap - idle_days) / 365) when idle longer than idle_days; checked: Sinner's last match on 12 Jul at
2154.1 gives 2092.8 on 15 Nov, elo.json's current). One snapshot per completed week with play, at most ten; the week in
progress folds into now (elo.json "current"), which stands in for the last completed week, so the move is against the
week before it (a Monday does not reset every move to zero). Earlier ranks are among today's top 100 (the history
covers only them). A tour with no event in play or to come is "offseason": its snapshots are the season's last ten
weeks of play, the last reading "Final".

Form (W/L, oldest first) is read from the same history: a rated match moves the rating up when won and down when lost,
after the inactivity pull (qualifying and Challenger / 125 matches included).

Groups in place of positions (season to date, the catalogue's qualifying rules as performers.py uses them): Serve on our
serve rating, Return on our return rating (qualified players: the season's match floor), and Hard, Clay and Grass on
that surface's Elo (players with the surface floor of matches on it), with the numbers a fan reads (holds, breaks, aces
where the tour publishes them, win rates, titles).
"""
from __future__ import annotations

import json
import logging
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from oddsmarkets.common import power as PW

log = logging.getLogger(__name__)

SITE, SPORT = "ace", "tennis"
TOURS = (("atp", "ATP"), ("wta", "WTA"))
TOP = 100
MEAN = 1500.0
# the kit's categorical tokens --c-1 .. --c-8 (docs/_design/tokens.css). Players have no team colours, and the climb needs
# lines told apart: the top 100 take them in Elo order (the top eight all differ); anyone else the site's own stable
# colour (docs/ace/assets/js/core.js playerColour: the same hash over the same palette)
PALETTE = ["#7d93ff", "#ff6a4d", "#5ec8f0", "#d4ff3a", "#c39be8", "#8fd16a", "#f28fb5", "#d9b38c"]
SURFACES = (("hard", "Hard"), ("clay", "Clay"), ("grass", "Grass"))
MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# stat slots: (label, [keys, the published stat first, our inferred one after], fmt, tip)
SERVE = [("Hold %", ["hold_real", "hold"], "pct1", "Service games held"),
         ("Aces/match", ["aces_pm"], "1", "Aces per match"),
         ("Serve pts won", ["spw_real", "spw_exp"], "pct1", "Serve points won"),
         ("BP saved", ["bp_saved_pct"], "pct0", "Break points saved"),
         ("Hold v top returners", ["hold_v_strong"], "pct1", "Hold % against the 20 best returners of the season")]
RETURN = [("Break %", ["brk_real", "brk"], "pct1", "Return games won"),
          ("Return pts won", ["rpw_real", "rpw_exp"], "pct1", "Return points won"),
          ("BP converted", ["bp_conv_pct"], "pct0", "Break points converted"),
          ("Break v top servers", ["brk_v_strong"], "pct1", "Break % against the 20 best servers of the season")]
SURF = [("Win %", ["win_pct"], "pct0", "Matches won on the surface"),
        ("Titles", ["titles"], "0", "Tour-level titles on the surface"),
        ("Hold %", ["hold_real", "hold"], "pct1", "Service games held on the surface"),
        ("Break %", ["brk_real", "brk"], "pct1", "Return games won on the surface")]
INFERRED = {"hold", "brk", "spw_exp", "rpw_exp"}
ROUND_WORDS = {"F": "the final", "SF": "the semi-finals"}


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
    except ValueError:
        return None


def colour(pid: str) -> str:
    h = 0
    for ch in str(pid):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return PALETTE[h % len(PALETTE)]


def _surname(short: str, name: str) -> str:
    s = str(short or "").strip()
    if ". " in s:
        return s.split(". ", 1)[1]
    parts = str(name or s).split()
    return parts[-1] if parts else s


def _abbr(sur: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", sur) if c.isalpha() and not unicodedata.combining(c))
    return s[:3].upper() or "?"


def _pull(r: float, last: date, when: date, idle: float, rho: float) -> float:
    """The site's inactivity pull to `when` (elo.ratings_at)."""
    gap = (when - last).days
    if gap > idle and rho < 1.0:
        return MEAN + (r - MEAN) * rho ** ((gap - idle) / 365.0)
    return r


def _at(rows: list, when: date, idle: float, rho: float) -> float | None:
    """The overall Elo going into `when`: the last row before it, pulled for idleness to that day."""
    best = None
    for h in rows:
        d = _day(h[0])
        if d is None or d >= when:
            break
        best = (d, PW.num(h[1]))
    if not best or best[1] is None:
        return None
    return _pull(best[1], best[0], when, idle, rho)


def _form(rows: list, idle: float, rho: float) -> tuple[str, str | None]:
    """(W/L of the last ten rated matches, oldest first; the current run as 'W7' / 'L3')."""
    out = []
    prev = None
    for h in rows:
        d, v = _day(h[0]), PW.num(h[1])
        if d is None or v is None:
            continue
        if prev is not None:
            pre = _pull(prev[1], prev[0], d, idle, rho)
            if abs(v - pre) >= 0.05:
                out.append("W" if v > pre else "L")
        prev = (d, v)
    if not out:
        return "", None
    k, n = out[-1], 0
    for x in reversed(out):
        if x != k:
            break
        n += 1
    return "".join(out[-10:]), f"{k}{n}"


def _place(rank, n: int, best: str) -> str | None:
    if rank is None or rank > 3:
        return None
    return (best[0].upper() + best[1:]) if rank == 1 else f"{PW.ordinal(rank)}-{best}"


def _where(ev: dict, T: str) -> tuple[str, str]:
    """('the Australian Open', 'at the Australian Open') or ('Paris', 'in Paris') for a week's result line ("Champion in
    Paris": not "Won ...", which the note would drop beside a winning run, as both start with the same word)."""
    lv, nm, city = ev.get("level"), str(ev.get("name") or ""), ev.get("city")
    if lv == "finals":
        n = f"the {T.upper()} Finals"
        return n, f"at {n}"
    if lv == "slam" or not city:
        return f"the {nm}", f"at the {nm}"
    return str(city), f"in {city}"


def _week_line(rows: list, events: dict, T: str) -> str | None:
    for eid, rnd, res in reversed(rows or []):
        ev = events.get(eid) or {}
        if not ev:
            continue
        what, at = _where(ev, T)
        if res == "W" and rnd == "F":
            return f"Champion {at}"
        if res == "L" and rnd == "F":
            return f"Runner-up {at}"
        if res == "A" and rnd in ROUND_WORDS:
            return f"Into {ROUND_WORDS[rnd]} {at}"
    return None


def _label(d: date) -> str:
    return f"{d.day} {MON[d.month - 1]}"


def _tidy(rows: list[dict]) -> None:
    low = ("Won", "Lost", "Up", "Down", "Best", "Worst", "New", "Gained", "Dropped", "Into", "Runner-up", "Champion")
    for t in rows:
        parts = str(t.get("note") or "").split("; ")
        for i in range(1, len(parts)):
            if parts[i].split(" ")[0] in low:
                parts[i] = parts[i][0].lower() + parts[i][1:]
        if t.get("note"):
            t["note"] = "; ".join(parts)


def _stats(slots: list, rows: list[dict], cap: int = 4) -> list[dict]:
    out = []
    for lab, keys, fmt, tip in slots:
        k = next((k for k in keys if any(PW.num((r.get("v") or {}).get(k)) is not None for r in rows)), None)
        if k is None:
            continue
        out.append({"key": k, "label": lab, "fmt": fmt, "tip": tip + (" (inferred from game and set scores)" if k in INFERRED else "")})
        if len(out) >= cap:
            break
    return out


def _groups(T: str, cat: dict, col: dict | None = None) -> dict | None:
    P = cat.get("players") or {}
    floor, sfl = cat.get("floor"), cat.get("surface_floor") or {}

    def row(pid, p, v):
        return {"id": str(pid), "name": p.get("name") or str(pid), "team": p.get("country") or "", "colour": (col or {}).get(pid) or colour(pid),
                "href": f"#/{T}/player/{quote(str(pid), safe='')}", "v": v}
    qual = [row(pid, p, p.get("values") or {}) for pid, p in P.items() if isinstance(p, dict) and p.get("qualified")]
    mt = f"{floor}+ tour-level main-draw matches this season" if floor else "the season's match floor"
    groups = []
    g = PW.group("serve", "Serve", qual, {"key": "serve_rating", "label": "Serve rating", "fmt": "+2", "dir": "higher",
                                         "tip": "Our serve strength on the logit scale: how much more than the tour baseline the player wins on serve, inferred from game and set scores by the serve/return model."},
                 _stats(SERVE, qual), short="Serve", min_text=mt)
    if g:
        groups.append(g)
    g = PW.group("return", "Return", qual, {"key": "return_rating", "label": "Return rating", "fmt": "+2", "dir": "higher",
                                           "tip": "Our return strength on the logit scale, inferred from game and set scores by the serve/return model."},
                 _stats(RETURN, qual), short="Return", min_text=mt)
    if g:
        groups.append(g)
    for s, lab in SURFACES:
        fl = sfl.get(s)
        rows = []
        for pid, p in P.items():
            vs = ((p or {}).get("values_surface") or {}).get(s) or {}
            if fl is None or (PW.num(vs.get("matches")) or 0) < fl:
                continue
            v = dict(vs)
            if PW.num(v.get("elo_surface")) is None:
                v["elo_surface"] = (p.get("values") or {}).get(f"elo_{s}")
            rows.append(row(pid, p, v))
        g = PW.group(s, lab, rows, {"key": "elo_surface", "label": f"{lab} Elo", "fmt": "0", "dir": "higher",
                                    "tip": f"Our Elo on {s} courts, from every rated match on {s}."},
                     _stats(SURF, rows), short=lab, min_text=f"{fl}+ tour-level matches on {s} this season" if fl else "")
        if g:
            groups.append(g)
    # tennis has serve, return and surfaces, not positions: the page and Home take these words (players.head, .cols)
    head = {"kicker": "Serve, return and surfaces", "title": "Best and worst on serve, return and every surface", "home": "serve, return, surfaces",
            "chips": "Group", "sub": "Every dot is a qualified player on the group’s headline number, worse to the left, better to the right; "
                                     "the top three in their colour, the bottom three in coral. Tap a group for its top five and bottom three."}
    return {"noun": "players", "head": head, "cols": {"team": "Nation"}, "groups": groups} if groups else None


def build_tour(data_root: Path, T: str, label: str, now: str | None = None) -> dict | None:
    ix = ((_read(data_root / "index.json") or {}).get("tours") or {}).get(T) or {}
    ej = _read(data_root / T / "elo.json") or {}
    cur = ej.get("current") or {}
    hist = ej.get("history") or {}
    if ej.get("ok") is False or not cur:
        return None
    prm = ej.get("params") or {}
    idle, rho = float(prm.get("idle_days") or 60.0), float(prm.get("rho") or 1.0)
    asof = _day(ej.get("as_of")) or datetime.now(timezone.utc).date()
    cat = _read(data_root / T / "players.json") or {}
    P = (cat.get("players") or {}) if cat.get("ok", True) else {}
    pidx = ((_read(data_root / T / "players_index.json") or {}).get("players")) or {}
    rk = _read(data_root / T / "rankings.json") or {}
    official = {str(r[1]): r[0] for r in rk.get("official") or [] if isinstance(r, list) and len(r) > 1}
    race = _read(data_root / T / "race.json") or {}
    year = int(ix.get("year") or cat.get("year") or asof.year)
    events = ((_read(data_root / T / str(year) / "events.json") or {}).get("events")) or {}
    for e in ix.get("events_now") or []:
        events.setdefault(e.get("event"), {"name": e.get("name"), "level": e.get("level")})
    in_play = bool(ix.get("events_now") or ix.get("upcoming") or race.get("remaining_events"))
    phase = "season" if in_play else "offseason"
    top = [p for p, _ in sorted(((p, v.get("rank") or 10 ** 6) for p, v in cur.items() if p in hist), key=lambda x: x[1])][:TOP]
    if not top:
        return None
    col = {p: PALETTE[i % len(PALETTE)] for i, p in enumerate(top)}
    # weeks of play: the Sundays that close a week with a rated match among these players
    last_sun = asof - timedelta(days=asof.weekday() + 1)        # the last completed week (Mon-Sun) before this one
    suns = set()
    for p in top:
        for h in hist.get(p) or []:
            d = _day(h[0])
            if d is not None:
                s_ = d + timedelta(days=6 - d.weekday())
                if s_ <= last_sun:
                    suns.add(s_)
    weeks = sorted(suns)[-PW.MAX_SNAPSHOTS:]
    if phase == "season":
        if not weeks:
            weeks = [last_sun]
        snaps = [{"key": f"w{d.isoformat()}", "label": _label(d), "date": d.isoformat()} for d in weeks]
        snaps[-1] = {"key": "now", "label": "Now", "date": asof.isoformat()}
    else:
        if not weeks:
            return None
        snaps = [{"key": f"w{d.isoformat()}", "label": _label(d), "date": d.isoformat()} for d in weeks]
        snaps[-1] = dict(snaps[-1], key="final", label="Final")
    n_s = len(snaps)
    raw = {}
    for p in top:
        rows = hist.get(p) or []
        rp = [_at(rows, d + timedelta(days=1), idle, rho) for d in weeks[:n_s]]
        if phase == "season":
            rp[-1] = PW.num((cur.get(p) or {}).get("all"))
        raw[p] = rp
    avg = []
    for i in range(n_s):
        xs = [raw[p][i] for p in top if raw[p][i] is not None]
        avg.append(sum(xs) / len(xs) if xs else None)
    # surface Elo ranks among the 100 (notes)
    srank = {s: PW._ranks({p: (cur.get(p) or {}).get(s) for p in top}) for s, _ in SURFACES}
    ft = race.get("finals_title") or {}
    fq = race.get("finals_qual") or {}
    week = race.get("week") or {}
    since = snaps[0]["label"] if n_s > 1 else ""
    ents, extras = [], {}
    for p in top:
        c = P.get(p) or {}
        pi = pidx.get(p) or []
        name = c.get("name") or (pi[0] if pi else p)
        short = c.get("short") or (pi[1] if len(pi) > 1 else name)
        sur = _surname(short, name)
        v = c.get("values") or {}
        form, streak = _form(hist.get(p) or [], idle, rho)
        rec = f"{int(v['wins'])}–{int(v['losses'])}" if PW.num(v.get("wins")) is not None and PW.num(v.get("losses")) is not None else None
        stats = [{"label": "Elo", "text": f"{PW.num((cur.get(p) or {}).get('all')):,.0f}"}]
        if official.get(p):
            stats.append({"label": "Ranking", "text": str(official[p])})
        if PW.num(v.get("titles")) is not None:
            stats.append({"label": "Titles", "text": str(int(v["titles"]))})
        ent = {"id": p, "name": name, "short": sur, "abbr": _abbr(sur), "colour": col[p],
               "href": f"#/{T}/player/{quote(str(p), safe='')}", "group": c.get("country") or (pi[2] if len(pi) > 2 else None),
               "rpath": [r - avg[i] if r is not None and avg[i] is not None else None for i, r in enumerate(raw[p])],
               "record": rec, "form": form or None, "streak": streak, "stats": stats}
        if phase == "season":
            if ft:
                pt = PW.num(ft.get(p))
                if pt is not None and pt >= 0.005:
                    ent["chance"] = {"label": "Finals title", "p": round(min(pt, 0.9999), 4)}
            else:
                pq = PW.num(fq.get(p))
                if pq is not None and 0.005 <= pq < 0.9995:
                    ent["chance"] = {"label": "Finals spot", "p": round(pq, 4)}
        ex = []
        wl = _week_line(week.get(p), events, T) if phase == "season" else None
        if wl:
            ex.append(wl)
        for s, lab in SURFACES:
            c_ = _place(srank[s].get(p), len(top), f"best {s}-court Elo in the top {TOP}")
            if c_:
                ex.append(c_)
        if since and raw[p][0] is not None and raw[p][-1] is not None and abs(raw[p][-1] - raw[p][0]) >= 15:
            d = raw[p][-1] - raw[p][0]
            ex.append(("Gained " if d > 0 else "Dropped ") + f"{abs(d):.0f} Elo points since {since}")
        extras[p] = ex
        ents.append(ent)
    rows = PW.teams_block(ents, snaps, step="week", rating_fmt="+0", extra_notes=extras)
    _tidy(rows)
    upd = now or ej.get("updated_at") or _now()
    rating = {"label": "Our rating", "short": "Elo", "unit": f"Elo points against the top-{TOP} average", "fmt": "+0",
              "tip": f"Our overall Elo from every rated match (tour level, qualifying and Challenger / 125), with the site’s pull "
                     f"towards the mean after a long lay-off, shown against the average of the top {TOP} (the Elo itself is beside it)."}
    notes = [("Each week’s ranking uses only the matches played up to the end of that week (Sunday); " +
              ("Final is where the season ended." if phase == "offseason" else "Now adds the matches played since.") +
              f" Earlier ranks are among today’s top {TOP}."),
             "Form: the last five rated matches, oldest first (qualifying and Challenger / 125 matches included).",
             "Groups: season to date, qualified players only (the rule is under each group)."]
    return PW.document(site=SITE, sport=SPORT, league=T, label=label, season=year, season_label=f"{year} season", updated_at=upd,
                       asof=asof.isoformat(), phase=phase, rating=rating, snapshots=snaps, teams=rows, step="week",
                       kind="players", noun="players", players=_groups(T, cat, col) if P else None, notes=notes)


def build(data_root: Path, now: str | None = None) -> dict | None:
    data_root = Path(data_root)
    docs = []
    for T, label in TOURS:
        try:
            d = build_tour(data_root, T, label, now)
        except Exception as exc:  # noqa: BLE001 - one tour failing keeps the other
            log.error("power %s failed: %s", T, exc)
            d = None
        if d:
            docs.append(d)
    if not docs:
        return None
    upd = now or max(str(d.get("updated_at") or "") for d in docs) or _now()
    # a tour that did not build keeps its last file on disk (no prune) until the next good run
    return PW.write(data_root, docs, site=SITE, sport=SPORT, updated_at=upd, default="atp", prune=len(docs) == len(TOURS))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "docs" / "ace" / "data"
    print(build(root))
