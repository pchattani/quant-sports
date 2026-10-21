"""Build The Quant home page data (docs/home/data/home.json + search.json) and copy the design kit.

The home page (docs/home/) is a static page in the shared design system. It reads one compact,
normalised file written here from the sport sites' already-built data trees:

    docs/site/data      football   (hub.json, competitions.json, <comp>/probs.json, market_odds.json)
    docs/paddock/data   F1         (index.json, markets.json, <year>/season.json)
    docs/hardwood/data  NBA/WNBA   (index.json, <league>/<season>/season.json)
    docs/ace/data       tennis     (index.json)
    docs/bullpen/data   MLB        (index.json, players_index.json)
    docs/gridiron/data  NFL        (index.json, <season>/season.json, players_index.json)
    docs/rink/data      NHL        (index.json, <season>/season.json, players_index.json)

Nothing is fetched from the network. Every sport is optional: a missing or broken tree is
logged and skipped, so the home page still builds with the sports that are present.

Live scores: the page refreshes scores in the browser from each sport's published index.json
(GitHub Pages sends Access-Control-Allow-Origin: *), so home.json only has to be as fresh as
the last build. See docs/_design/README.md.

Usage:
    python scripts/build_home.py                  # links point at the public GitHub Pages sites
    python scripts/build_home.py --links local    # links point at ../site/, ../paddock/ ... (preview)
    python scripts/build_home.py --links local --with-pending   # also the sites not launched yet (local preview)

Sites not launched yet (PENDING, e.g. The Quant Campus) are left out of home.json and search.json unless their key
is in LAUNCHED or --with-pending is given, so the live home page never links a Pages site that does not exist.
The kit hides them the same way (QK.SPORTS drops `pending` entries outside local preview).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "home"

PUBLIC = "https://pchattani.github.io/the-quant-{}/"
SPORTS = [
    # key, folder, public repo suffix, label, site name
    ("football", "site", "footballer", "Football", "The Quant Footballer"),
    ("f1", "paddock", "paddock", "Formula 1", "The Quant Paddock"),
    ("basketball", "hardwood", "hardwood", "Basketball", "The Quant Hardwood"),
    ("tennis", "ace", "ace", "Tennis", "The Quant Ace"),
    ("baseball", "bullpen", "bullpen", "Baseball", "The Quant Bullpen"),
    ("nfl", "gridiron", "gridiron", "NFL", "The Quant Gridiron"),
    ("hockey", "rink", "rink", "NHL", "The Quant Rink"),
]
# Built but not launched (no public Pages site yet): only with --with-pending or once listed in LAUNCHED.
PENDING = [
    ("college", "campus", "campus", "College", "The Quant Campus"),
]
LAUNCHED: set[str] = {"college"}   # The Quant Campus, launched 21 Oct 2026

# Football competitions in rough order of how many fans care; used to pick which fixtures
# make the home page when a day has a hundred of them.
FOOTBALL_PRIORITY = [
    "champions-league", "premier-league", "la-liga", "serie-a", "bundesliga", "ligue-1",
    "world-cup", "euro", "copa-america", "nations-league", "europa-league", "libertadores",
    "club-world-cup", "conference-league", "mls", "brasileirao", "eredivisie", "primeira-liga",
    "liga-mx", "saudi-pro-league", "liga-argentina", "sudamericana", "fa-cup", "copa-del-rey",
    "coppa-italia", "dfb-pokal", "coupe-de-france", "efl-cup", "belgian-pro-league",
]
TITLE_LEAGUES = ["premier-league", "la-liga", "serie-a", "bundesliga", "ligue-1", "mls",
                 "brasileirao", "eredivisie", "primeira-liga", "liga-mx", "saudi-pro-league"]


def surname(name):
    """'Lionel Messi' -> 'Messi'; keeps particles ('Kevin De Bruyne' -> 'De Bruyne'); 'A. Sabalenka' -> 'Sabalenka'."""
    if not name:
        return name
    parts = str(name).split()
    if len(parts) < 2:
        return name
    lower = {"de", "da", "van", "von", "der", "di", "le", "la", "del", "dos", "el"}
    i = len(parts) - 1
    while i > 1 and parts[i - 1].lower() in lower:
        i -= 1
    return " ".join(parts[i:])


def nice_date(s):
    d = parse_ts(s)
    return f"{d:%a} {d.day} {d:%b}" if d else (s or "")


def log(msg: str) -> None:
    print("[build_home] " + msg, file=sys.stderr)


def load(path: Path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as exc:  # broken JSON must not stop the other sports
        log(f"could not read {path}: {exc}")
        return None


def r4(x):
    return None if x is None else round(float(x), 4)


def parse_ts(s):
    if not s:
        return None
    s = str(s)
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def norm_status(s) -> str:
    s = str(s or "").lower()
    if s in ("finished", "final", "post", "done", "closed", "ft", "complete", "completed"):
        return "final"
    if s in ("live", "in", "inprogress", "in_progress", "running"):
        return "live"
    if s in ("postponed", "cancelled", "canceled", "suspended"):
        return "off"
    return "pre"


class Ctx:
    def __init__(self, links: str, now: datetime):
        self.links = links
        self.now = now
        self.lo = now - timedelta(hours=40)
        self.hi = now + timedelta(days=5)

    def base(self, folder: str, repo: str) -> str:
        return f"../{folder}/" if self.links == "local" else PUBLIC.format(repo)


def team(name, abbr=None, colour=None, logo=None, href=None):
    t = {"name": name}
    if abbr:
        t["abbr"] = abbr
    if colour:
        t["colour"] = colour
    if logo:
        t["logo"] = logo
    if href:
        t["href"] = href
    return t


def game(sport, league, gid, start, status, home, away, hs=None, as_=None, **kw):
    g = {"sport": sport, "league": league, "id": str(gid), "start": start,
         "status": norm_status(status), "home": home, "away": away}
    if hs is not None:
        g["hs"] = hs
    if as_ is not None:
        g["as"] = as_
    for k, v in kw.items():
        if v is not None and v != "":
            g[k] = v
    return g


def in_window(ctx: Ctx, g) -> bool:
    d = parse_ts(g.get("start"))
    if g["status"] == "live":
        return True
    return d is not None and ctx.lo <= d <= ctx.hi


def pick_games(ctx, games, n_final=6, n_pre=10, key=None):
    games = [g for g in games if in_window(ctx, g) and g["status"] != "off"]
    live = [g for g in games if g["status"] == "live"]
    fin = sorted([g for g in games if g["status"] == "final"], key=lambda g: g["start"], reverse=True)
    pre = sorted([g for g in games if g["status"] == "pre"], key=lambda g: g["start"])
    if key:
        fin = sorted(fin, key=key)
        pre = sorted(pre, key=key)
    return live + fin[:n_final] + pre[:n_pre]


def gap_row(sport, label, model, market, href=None, kind="game", detail=None):
    if model is None or market is None:
        return None
    r = {"sport": sport, "label": label, "model": r4(model), "market": r4(market),
         "diff": r4(model - market), "kind": kind}
    if href:
        r["href"] = href
    if detail:
        r["detail"] = detail
    return r


# ───────────────────────────────────────────────────────────── football
def build_football(ctx: Ctx, base: str, out: dict):
    d = DOCS / "site" / "data"
    hub = load(d / "hub.json")
    comps = load(d / "competitions.json") or {}
    if not hub:
        raise RuntimeError("hub.json missing")
    pri = {s: i for i, s in enumerate(FOOTBALL_PRIORITY)}
    comp_names = {c["slug"]: (c.get("short_name") or c.get("name")) for c in comps.get("competitions", [])}

    def crest(p):
        return base + p if p else None

    def club_href(p, slug):
        if p and "/crests/" in p:
            tid = p.rsplit("/", 1)[-1].split(".")[0]
            return base + "#/club/" + tid + "?c=" + slug
        return None

    seen, games = set(), []
    days = hub.get("days") or {}
    for day in sorted(days):
        for m in days[day]:
            if m["id"] in seen:
                continue
            seen.add(m["id"])
            cr = m.get("crests") or [None, None]
            mod = m.get("model") or {}
            g = game("football", m.get("comp_name") or m["comp"], m["id"], m["date"], m.get("status"),
                     team(m["home"], logo=crest(cr[0]), href=club_href(cr[0], m["comp"])),
                     team(m["away"], logo=crest(cr[1]), href=club_href(cr[1], m["comp"])),
                     m.get("hs"), m.get("as"),
                     p_home=r4(mod.get("h")), p_draw=r4(mod.get("d")), p_away=r4(mod.get("a")),
                     xg=m.get("xg"), href=base + "#/" + m["comp"] + "/match/" + str(m["id"]),
                     note=(str(m.get("round")).upper() if isinstance(m.get("round"), str) else
                           ("Round " + str(m["round"]) if m.get("round") else None)),
                     rank=pri.get(m["comp"], 99), comp=m["comp"])
            games.append(g)
    picked = pick_games(ctx, games, n_final=8, n_pre=14,
                        key=lambda g: (g.get("rank", 99), g["start"]))
    for g in picked:
        g.pop("rank", None)
    out["games"].extend(picked)

    # Title races: model v market outrights per big league
    titles, gaps = [], []
    for slug in TITLE_LEAGUES:
        probs = load(d / slug / "probs.json")
        mk = load(d / slug / "market_odds.json") or {}
        if not probs:
            continue
        outr = (mk.get("outrights") or {})
        mkt = {t["team"]: t.get("market") for t in (outr.get("teams") or [])} if outr.get("available") else {}
        rows = []
        for t in sorted(probs.get("teams", []), key=lambda t: -(t.get("p_title") or 0))[:6]:
            rows.append({"name": t["team"], "p": r4(t.get("p_title")), "market": r4(mkt.get(t["team"])),
                         "exp_pts": t.get("exp_pts")})
        titles.append({"league": comp_names.get(slug, slug), "slug": slug, "rows": rows,
                       "href": base + "#/" + slug + "/probs"})
        for t in (outr.get("teams") or [])[:8]:
            gr = gap_row("football", f"{t['team']} to win {comp_names.get(slug, slug)}", t.get("model"),
                         t.get("market"), base + "#/" + slug + "/market", kind="title")
            if gr:
                gaps.append(gr)
    out["charts"]["football_titles"] = titles

    favs = []
    for c in comps.get("competitions", []):
        if c.get("kind") == "league" and c.get("p_favourite") and c.get("favourite") and c.get("games_played"):
            favs.append({"league": c.get("short_name") or c["name"], "team": c["favourite"],
                         "p": r4(c["p_favourite"]), "played": c.get("games_played"),
                         "total": c.get("games_total"), "href": base + "#/" + c["slug"]})
    favs.sort(key=lambda r: -r["p"])
    out["charts"]["football_favourites"] = favs[:14]

    lead = hub.get("leaders") or {}
    goals = []
    for p in (lead.get("goals") or [])[:10]:
        goals.append({"name": p["name"], "team": p.get("team"), "league": p.get("comp_name"),
                      "value": p.get("value"), "xg": p.get("xg"),
                      "href": base + "#/player/" + str(p["id"]) + "?c=" + p.get("comp", "")})
    out["leaders"]["football"] = {"title": "Goals", "unit": "goals", "rows": goals}
    out["gaps"].extend(gaps)

    n_live = sum(1 for g in games if g["status"] == "live")
    today = hub.get("today")
    n_today = sum(1 for g in games if (g["start"] or "")[:10] == today)
    top = goals[0] if goals else None
    sp = {"phase": "In season", "status": f"{n_today} matches today" + (f" · {n_live} live" if n_live else ""),
          "kpis": [{"label": "Comps", "value": len(comps.get("competitions", []))},
                   {"label": "Today", "value": n_today, "sub": "matches"},
                   {"label": "Top scorer", "value": surname(top["name"]) if top else "—",
                    "sub": f"{top['value']} goals" if top else None}],
          "updated_at": hub.get("updated_at")}
    if top and top.get("xg"):
        out["stats"].append({"sport": "football", "kicker": "Finishing above the model",
                             "value": f"+{top['value'] - top['xg']:.1f}",
                             "unit": "goals over xG",
                             "text": f"{top['name']} has {top['value']} goals from {top['xg']:.1f} expected goals "
                                     f"for {top['team']} this season.",
                             "href": top["href"]})
    if titles:
        t0 = titles[0]
        if t0["rows"] and t0["rows"][0].get("market"):
            r0 = t0["rows"][0]
            out["stats"].append({"sport": "football", "kicker": f"{t0['league']} title",
                                 "value": f"{r0['p'] * 100:.0f}%", "unit": "model title odds",
                                 "text": f"The model makes {r0['name']} {r0['p'] * 100:.0f}% to win the "
                                         f"{t0['league']}; the market says {r0['market'] * 100:.0f}%.",
                                 "href": t0["href"]})
    return sp


# ───────────────────────────────────────────────────────────── F1
def build_f1(ctx: Ctx, base: str, out: dict):
    d = DOCS / "paddock" / "data"
    idx = load(d / "index.json")
    if not idx:
        raise RuntimeError("index.json missing")
    mk = load(d / "markets.json") or {}
    year = idx.get("current_season")
    season = load(d / str(year) / "season.json") or {}
    teams = idx.get("teams") or {}
    drivers = idx.get("drivers") or {}

    def dname(k):
        return (drivers.get(k) or {}).get("name") or (season.get("names") or {}).get(k) or k

    def dcol(k):
        return (teams.get((drivers.get(k) or {}).get("team")) or {}).get("colour")

    nx = idx.get("next") or {}
    race = None
    if nx:
        nr = mk.get("next_race") or {}
        model = nr.get("model") or {}
        prices = nr.get("prices") or {}
        field = sorted(set(model) | set(prices), key=lambda k: -(model.get(k) or 0))[:8]
        race = {"name": nx.get("name"), "round": nx.get("round"), "year": nx.get("year"),
                "date": nx.get("date"), "circuit": (nx.get("circuit") or {}).get("name"),
                "locality": (nx.get("circuit") or {}).get("locality"),
                "country": (nx.get("circuit") or {}).get("country"),
                "sessions": nx.get("sessions"),
                "href": base + "#/race/" + str(nx.get("year")) + "/" + str(nx.get("round")),
                "field": [{"name": dname(k), "code": (drivers.get(k) or {}).get("code"), "colour": dcol(k),
                           "p": r4(model.get(k)), "market": r4(prices.get(k)),
                           "href": base + "#/driver/" + k} for k in field]}
        for k in field[:6]:
            gr = gap_row("f1", f"{dname(k)} to win the {nx.get('name')}", model.get(k), prices.get(k),
                         race["href"], kind="race")
            if gr:
                out["gaps"].append(gr)
        sess = nx.get("sessions") or {}
        out["games"].append(game("f1", "Formula 1", f"{nx.get('year')}-{nx.get('round')}",
                                 sess.get("race") or nx.get("date"), "pre",
                                 team(nx.get("name") or "Grand Prix"), team((nx.get("circuit") or {}).get("name") or ""),
                                 href=race["href"], note=f"Round {nx.get('round')}", event=True,
                                 fav=race["field"][0]["name"] if race["field"] else None,
                                 fav_p=race["field"][0]["p"] if race["field"] else None))
    out["charts"]["f1_next_race"] = race

    prog = season.get("progression") or {}
    st = (season.get("standings") or {}).get("drivers") or []
    lines = []
    seen_team = set()
    for row in st[:5]:
        k = row["driver"]
        pts = (prog.get("drivers") or {}).get(k)
        if pts:
            tm_ = row.get("team")
            lines.append({"name": dname(k), "code": (drivers.get(k) or {}).get("code"), "colour": dcol(k),
                          "dash": tm_ in seen_team,  # team-mates share a colour; the second is dashed
                          "points": pts, "href": base + "#/driver/" + k})
            seen_team.add(tm_)
    out["charts"]["f1_title_race"] = {"rounds": prog.get("rounds") or [], "series": lines,
                                      "year": year, "href": base + "#/season/" + str(year)}

    champ = (season.get("championship") or {}).get("drivers") or {}
    title = sorted(champ.items(), key=lambda kv: -(kv[1].get("p_title") or 0))[:6]
    dt = mk.get("drivers_title") or {}
    out["futures"]["f1"] = {"title": "Drivers' title", "rows": [
        {"name": dname(k), "p": r4(v.get("p_title")), "market": r4((dt.get("prices") or {}).get(k)),
         "colour": dcol(k), "href": base + "#/driver/" + k} for k, v in title]}

    last = idx.get("last") or {}
    leader = st[0] if st else None
    second = st[1] if len(st) > 1 else None
    meta = (idx.get("seasons_meta") or {}).get(str(year)) or {}
    sp = {"phase": f"Round {meta.get('completed', '?')} of {meta.get('rounds', '?')}",
          "status": (f"Next: {nx.get('name')} · {nice_date(nx.get('date'))}" if nx else "Season complete"),
          "kpis": [{"label": "Leader", "value": surname(dname(leader["driver"])) if leader else "—",
                    "sub": f"{leader['points']:.0f} pts" if leader else None},
                   {"label": "Gap to P2", "value": f"{leader['points'] - second['points']:.0f}" if leader and second else "—",
                    "sub": "points"},
                   {"label": "Last win", "value": surname(dname(last.get("winner"))) if last.get("winner") else "—",
                    "sub": (last.get("name") or "").replace(" Grand Prix", " GP")}],
          "updated_at": idx.get("updated_at")}
    if leader and second and title:
        out["stats"].append({"sport": "f1", "kicker": "Championship lead",
                             "value": f"{leader['points'] - second['points']:.0f}", "unit": "points clear",
                             "text": f"{dname(leader['driver'])} leads by {leader['points'] - second['points']:.0f} "
                                     f"points with {meta.get('rounds', 0) - meta.get('completed', 0)} rounds left; "
                                     f"title odds {(title[0][1].get('p_title') or 0) * 100:.1f}%.",
                             "href": base + "#/season/" + str(year)})
    lead_rows = [{"name": dname(r["driver"]), "team": (teams.get(r.get("team")) or {}).get("name"),
                  "value": r.get("points"), "sub": f"{r.get('wins', 0)} wins", "colour": dcol(r["driver"]),
                  "href": base + "#/driver/" + r["driver"]} for r in st[:10]]
    out["leaders"]["f1"] = {"title": "Drivers' points", "unit": "pts", "rows": lead_rows}
    for k, v in drivers.items():
        out["search"].append(["f1", v.get("name"), "Driver · " + ((teams.get(v.get("team")) or {}).get("name") or ""),
                              base + "#/driver/" + k])
    for k, v in teams.items():
        out["search"].append(["f1", v.get("name"), "Constructor", base + "#/team/" + k])
    return sp


# ───────────────────────────────────────────────────────────── basketball
def build_basketball(ctx: Ctx, base: str, out: dict):
    d = DOCS / "hardwood" / "data"
    idx = load(d / "index.json")
    if not idx:
        raise RuntimeError("index.json missing")
    sp_status, kpis = [], []
    futures = {}
    for L, lg in (idx.get("leagues") or {}).items():
        teams = lg.get("teams") or {}
        LU = L.upper()

        def tm(tid):
            t = teams.get(str(tid)) or {}
            return team(t.get("short") or t.get("name") or str(tid), t.get("abbr"), t.get("colour"),
                        href=base + "#/" + L + "/team/" + str(tid))

        seen, games = set(), []
        for g in (lg.get("today") or []) + (lg.get("next_games") or []) + (lg.get("last_games") or []):
            if g["id"] in seen:
                continue
            seen.add(g["id"])
            m, mk = g.get("model") or {}, g.get("market") or {}
            ser = g.get("series") or {}
            note = ser.get("round") and (ser["round"] + (f" · G{ser['game']}" if ser.get("game") else ""))
            games.append(game("basketball", LU, g["id"], g["date"], g["status"], tm(g["home"]), tm(g["away"]),
                              g.get("hs"), g.get("as"), p_home=r4(m.get("p_home")), market_home=r4(mk.get("p_home")),
                              spread=mk.get("spread_home"), total=m.get("total"), clock=g.get("clock"),
                              period=g.get("period"), wp_home=r4(g.get("wp_home")), note=note,
                              href=base + "#/" + L + "/game/" + str(g["id"])))
            if norm_status(g["status"]) == "pre":
                gr = gap_row("basketball", f"{tm(g['away'])['name']} @ {tm(g['home'])['name']} ({LU})",
                             m.get("p_home"), mk.get("p_home"), base + "#/" + L + "/game/" + str(g["id"]),
                             detail="home win")
                if gr:
                    out["gaps"].append(gr)
        out["games"].extend(pick_games(ctx, games, 4, 6))
        season = load(d / L / str(lg.get("current_season")) / "season.json") or {}
        sim = (season.get("sim") or {}).get("teams") or {}
        rows = sorted(sim.items(), key=lambda kv: -(kv[1].get("p_title") or 0))
        rows = [(k, v) for k, v in rows if (v.get("p_title") or 0) > 0][:8]
        if rows:
            futures[L] = {"title": f"{LU} title", "rows": [
                {"name": (teams.get(k) or {}).get("name") or k, "abbr": (teams.get(k) or {}).get("abbr"),
                 "p": r4(v.get("p_title")), "colour": (teams.get(k) or {}).get("colour"),
                 "href": base + "#/" + L + "/team/" + k} for k, v in rows]}
        sp_status.append(f"{LU} {lg.get('phase')}")
        if rows:
            k0 = rows[0][0]
            kpis.append({"label": f"{LU} fav", "value": (teams.get(k0) or {}).get("short") or k0,
                         "sub": f"{(rows[0][1].get('p_title') or 0) * 100:.0f}% title"})
        for k, t in teams.items():
            out["search"].append(["basketball", t.get("name"), f"{LU} team", base + "#/" + L + "/team/" + k])
        power = season.get("power") or []
        if L == "nba" and power:
            out["charts"]["nba_power"] = {"title": "NBA preseason net ratings", "rows": [
                {"name": (teams.get(p[0]) or {}).get("short") or p[0], "abbr": (teams.get(p[0]) or {}).get("abbr"),
                 "value": p[1], "colour": (teams.get(p[0]) or {}).get("colour"),
                 "href": base + "#/nba/team/" + p[0]} for p in power]}
    futures_ordered = [futures[k] for k in ("wnba", "nba") if k in futures]
    if futures_ordered:
        out["futures"]["basketball"] = futures_ordered[0]
        if len(futures_ordered) > 1:
            out["futures"]["basketball_2"] = futures_ordered[1]
    return {"phase": " · ".join(sp_status), "status": " · ".join(sp_status), "kpis": kpis[:3],
            "updated_at": idx.get("updated_at")}


# ───────────────────────────────────────────────────────────── tennis
def build_tennis(ctx: Ctx, base: str, out: dict):
    d = DOCS / "ace" / "data"
    idx = load(d / "index.json")
    if not idx:
        raise RuntimeError("index.json missing")
    kpis, status = [], []
    for T, tour in (idx.get("tours") or {}).items():
        TU = T.upper()
        names = tour.get("names") or {}
        ev = {e["event"]: e for e in tour.get("events_now") or []}
        seen, games = set(), []
        for m in (tour.get("live") or []) + (tour.get("today") or []) + (tour.get("recent") or []) + (tour.get("upcoming") or []):
            if m["id"] in seen:
                continue
            seen.add(m["id"])
            n = m.get("n") or [names.get(m.get("p1")), names.get(m.get("p2"))]
            sets = m.get("sets") or []
            hs = as_ = None
            if sets and norm_status(m.get("status")) != "pre":
                hs = sum(1 for s in sets if s[0] is not None and s[1] is not None and s[0] > s[1])
                as_ = sum(1 for s in sets if s[0] is not None and s[1] is not None and s[1] > s[0])
            mod, mk = m.get("model") or {}, m.get("market") or {}
            e = ev.get(m.get("event")) or {}
            start = m.get("date")
            if start and len(start) == 16:
                start += ":00Z"
            g = game("tennis", f"{TU} · {e.get('name') or m.get('event')}", m["id"], start, m.get("status"),
                     team(n[0], href=base + "#/" + T + "/player/" + str(m.get("p1"))),
                     team(n[1], href=base + "#/" + T + "/player/" + str(m.get("p2"))),
                     hs, as_, p_home=r4(mod.get("p1")), market_home=r4(mk.get("p1")),
                     sets=[[s[0], s[1]] for s in sets if s[0] is not None] if sets else None,
                     note=m.get("round"), href=base + "#/" + T + "/match/" + str(m["id"]), players=True)
            games.append(g)
            if norm_status(m.get("status")) == "pre":
                gr = gap_row("tennis", f"{n[0]} v {n[1]} ({TU} {m.get('round')})", mod.get("p1"), mk.get("p1"),
                             g["href"], detail="first-named player wins")
                if gr:
                    out["gaps"].append(gr)
        out["games"].extend(pick_games(ctx, games, 3, 5))
        elo = (tour.get("elo_top") or {}).get("all") or []
        out["leaders"]["tennis_" + T] = {"title": f"{TU} Elo", "unit": "Elo", "rows": [
            {"name": names.get(p[0]) or p[0], "value": round(p[1]), "href": base + "#/" + T + "/player/" + p[0]}
            for p in elo[:10]]}
        if elo:
            kpis.append({"label": f"{TU} Elo 1", "value": surname(names.get(elo[0][0]) or elo[0][0]),
                         "sub": f"{elo[0][1]:.0f}"})
        for e in tour.get("events_now") or []:
            status.append(e.get("name"))
        for pid, nm in names.items():
            out["search"].append(["tennis", nm, f"{TU} player", base + "#/" + T + "/player/" + pid])
    if len(kpis) < 3:
        kpis.append({"label": "Events", "value": len(status), "sub": "in play"})
    return {"phase": "In season", "status": " · ".join(status) or "Between events", "kpis": kpis,
            "updated_at": idx.get("updated_at")}


# ───────────────────────────────────────────────────────────── baseball
def build_baseball(ctx: Ctx, base: str, out: dict):
    d = DOCS / "bullpen" / "data"
    idx = load(d / "index.json")
    if not idx:
        raise RuntimeError("index.json missing")
    pidx = load(d / "players_index.json") or {}
    teams = idx.get("teams") or {}

    def tm(tid):
        t = teams.get(str(tid)) or {}
        return team(t.get("short") or t.get("name") or str(tid), t.get("abbr"), t.get("colour"),
                    href=base + "#/mlb/team/" + str(tid))

    seen, games = set(), []
    for g in (idx.get("today") or []) + (idx.get("recent") or []) + (idx.get("upcoming") or []):
        if g["gpk"] in seen:
            continue
        seen.add(g["gpk"])
        m, mk = g.get("model") or {}, g.get("market") or {}
        ser = g.get("series") or {}
        note = ser.get("desc") and (ser["desc"].replace("Championship Series", "CS").replace("Division Series", "DS")
                                    + (f" · G{ser['game']}" if ser.get("game") else ""))
        games.append(game("baseball", "MLB", g["gpk"], g.get("start"), g.get("status"), tm(g["home"]), tm(g["away"]),
                          g.get("hs"), g.get("as"), p_home=r4(m.get("p_home")), market_home=r4(mk.get("p_home")),
                          total=m.get("total"), period=g.get("inning"), wp_home=r4(g.get("wp_home")), note=note,
                          href=base + "#/mlb/game/" + str(g["gpk"])))
        if norm_status(g.get("status")) == "pre":
            gr = gap_row("baseball", f"{tm(g['away'])['name']} @ {tm(g['home'])['name']}", m.get("p_home"),
                         mk.get("p_home"), base + "#/mlb/game/" + str(g["gpk"]), detail="home win")
            if gr:
                out["gaps"].append(gr)
    out["games"].extend(pick_games(ctx, games, 3, 4))
    ps = idx.get("postseason") or {}
    pteams = ps.get("teams") or {}
    rows = sorted(pteams.items(), key=lambda kv: -(kv[1].get("p_ws") or 0))
    rows = [(k, v) for k, v in rows if (v.get("p_ws") or 0) > 0]
    if rows:
        out["futures"]["baseball"] = {"title": "World Series", "rows": [
            {"name": (teams.get(k) or {}).get("name") or v.get("name"), "abbr": (teams.get(k) or {}).get("abbr"),
             "p": r4(v.get("p_ws")), "colour": (teams.get(k) or {}).get("colour"),
             "href": base + "#/mlb/team/" + k} for k, v in rows]}
    for s in ps.get("series") or []:
        if not s.get("done") and s.get("market"):
            a, b = s["teams"]
            gr = gap_row("baseball", f"{tm(a)['name']} to win the {s.get('round_name')}", (s.get("p") or [None])[0],
                         s["market"][0], base + "#/postseason", kind="series",
                         detail=f"series {s['wins'][0]}-{s['wins'][1]}")
            if gr:
                out["gaps"].append(gr)
    series = []
    for s in ps.get("series") or []:
        if not s.get("done"):
            a, b = s["teams"]
            series.append({"round": s.get("round_name"), "a": tm(a), "b": tm(b), "wins": s.get("wins"),
                           "p": [r4(x) for x in (s.get("p") or [])], "best_of": s.get("best_of"),
                           "market": s.get("market")})
    out["charts"]["mlb_series"] = series

    lead = idx.get("leaders") or {}
    war = []
    for pid, v in (lead.get("h_war") or [])[:8]:
        p = pidx.get(str(pid)) or []
        war.append({"name": p[0] if p else pid, "team": (teams.get(str(p[1])) or {}).get("abbr") if len(p) > 1 else None,
                    "value": v, "href": base + "#/player/" + str(pid)})
    out["leaders"]["baseball"] = {"title": "Hitter WAR", "unit": "WAR", "rows": war}
    for k, t in teams.items():
        out["search"].append(["baseball", t.get("name"), "MLB team · " + (t.get("division") or ""),
                              base + "#/mlb/team/" + k])
    nxt = next((s for s in series), None)
    kp = [{"label": "WS fav", "value": (teams.get(rows[0][0]) or {}).get("short") if rows else "—",
           "sub": f"{rows[0][1]['p_ws'] * 100:.0f}%" if rows else None}]
    if nxt:
        kp.append({"label": nxt["round"].replace("League Championship Series", "LCS").replace("Division Series", "DS"),
                   "value": f"{nxt['a'].get('abbr')} {nxt['wins'][0]}-{nxt['wins'][1]} {nxt['b'].get('abbr')}",
                   "sub": f"{nxt['a'].get('abbr')} {nxt['p'][0] * 100:.0f}% to advance" if nxt["p"] else None})
    if war:
        kp.append({"label": "WAR leader", "value": surname(war[0]["name"]), "sub": f"{war[0]['value']} WAR"})
    if rows:
        k0, v0 = rows[0]
        out["stats"].append({"sport": "baseball", "kicker": "World Series odds",
                             "value": f"{v0['p_ws'] * 100:.0f}%", "unit": (teams.get(k0) or {}).get("short"),
                             "text": f"The {(teams.get(k0) or {}).get('name')} are the model's World Series "
                                     f"favourite after 20,000 simulations of the bracket.",
                             "href": base + "#/postseason"})
    return {"phase": (idx.get("phase") or "").capitalize(), "status": (nxt["round"] if nxt else idx.get("phase")),
            "kpis": kp, "updated_at": idx.get("updated_at")}


# ───────────────────────────────────────────────────────────── NFL
def build_nfl(ctx: Ctx, base: str, out: dict):
    d = DOCS / "gridiron" / "data"
    idx = load(d / "index.json")
    if not idx:
        raise RuntimeError("index.json missing")
    pidx = load(d / "players_index.json") or {}
    teams = idx.get("teams") or {}

    def tm(a):
        t = teams.get(a) or {}
        return team(t.get("name", a).split(" ")[-1] if t.get("name") else a, a, t.get("colour"),
                    href=base + "#/team/" + a)

    seen, games = set(), []
    for g in (idx.get("live") or []) + (idx.get("games") or []) + (idx.get("recent") or []):
        if g["game_id"] in seen:
            continue
        seen.add(g["game_id"])
        m, mk, ln = g.get("model") or {}, g.get("market") or {}, g.get("line") or {}
        games.append(game("nfl", "NFL", g["game_id"], g["kickoff"], g["status"], tm(g["home"]), tm(g["away"]),
                          g.get("hs"), g.get("as"), p_home=r4(m.get("p_home")), market_home=r4(mk.get("p_home")),
                          spread=ln.get("spread_home"), model_spread=m.get("spread"), total=ln.get("total"),
                          period=g.get("qtr"), clock=g.get("clock"), wp_home=r4(g.get("wp_home")),
                          note=f"Week {g.get('week')}", href=base + "#/game/" + g["game_id"]))
        if norm_status(g["status"]) == "pre":
            gr = gap_row("nfl", f"{tm(g['away'])['name']} @ {tm(g['home'])['name']}", m.get("p_home"),
                         mk.get("p_home"), base + "#/game/" + g["game_id"], detail="home win")
            if gr:
                out["gaps"].append(gr)
    out["games"].extend(pick_games(ctx, games, 4, 10))
    for gp in (idx.get("gaps") or [])[:8]:
        if not gp.get("name"):
            continue  # game-level gaps are already covered from the games list
        kind, _, ab = gp["name"].partition(": ")
        nm = (teams.get(ab) or {}).get("name", ab)
        parts = kind.split("_")
        if kind == "playoffs":
            label = f"{nm} make the playoffs"
        elif parts[0] == "div":
            label = f"{nm} win the {' '.join(parts[1:]).upper()}"
        elif parts[0] == "seed1":
            label = f"{nm} take the {parts[1].upper()} No. 1 seed"
        elif parts[0] == "conf":
            label = f"{nm} win the {parts[1].upper()}"
        else:
            label = f"{nm}: {kind}"
        gr = gap_row("nfl", label, gp["model"], gp["market"], base + "#/markets", kind="futures")
        if gr:
            out["gaps"].append(gr)
    po = idx.get("playoff_odds") or {}
    rows = sorted(po.items(), key=lambda kv: -(kv[1].get("p_sb") or 0))[:8]
    out["futures"]["nfl"] = {"title": "Super Bowl", "rows": [
        {"name": (teams.get(k) or {}).get("name", k), "abbr": k, "p": r4(v.get("p_sb")),
         "p2": r4(v.get("p_playoffs")), "colour": (teams.get(k) or {}).get("colour"),
         "href": base + "#/team/" + k} for k, v in rows]}

    season = load(d / str(idx.get("season")) / "season.json") or {}
    ratings = season.get("ratings") or {}
    movers = []
    for ab, r in ratings.items():
        h = r.get("history") or []
        if len(h) >= 2:
            movers.append((ab, h[-1][1] - h[0][1], h))
    movers.sort(key=lambda x: -abs(x[1]))
    out["charts"]["nfl_movers"] = {"title": "Biggest rating moves this season", "unit": "points v average team",
                                   "href": base + "#/teams", "series": [
        {"name": (teams.get(ab) or {}).get("name", ab), "abbr": ab, "colour": (teams.get(ab) or {}).get("colour"),
         "delta": round(dlt, 2), "weeks": [x[0] for x in h], "net": [x[1] for x in h],
         "href": base + "#/team/" + ab} for ab, dlt, h in movers[:6]]}

    lead = idx.get("leaders") or {}
    qbs = []
    for pid, v in (lead.get("qb_composite") or [])[:8]:
        p = pidx.get(pid) or []
        qbs.append({"name": p[0] if p else pid, "team": p[1] if len(p) > 1 else None, "value": v,
                    "colour": (teams.get(p[1]) or {}).get("colour") if len(p) > 1 else None,
                    "href": base + "#/player/" + pid})
    out["leaders"]["nfl"] = {"title": "QB composite", "unit": "", "rows": qbs}
    for k, t in teams.items():
        out["search"].append(["nfl", t.get("name"), "NFL team · " + (t.get("division") or ""), base + "#/team/" + k])
    if movers:
        ab, dlt, h = movers[0]
        out["stats"].append({"sport": "nfl", "kicker": "Biggest mover",
                             "value": f"{dlt:+.1f}", "unit": "rating points",
                             "text": f"The {(teams.get(ab) or {}).get('name', ab)} have moved {dlt:+.1f} points "
                                     f"per game against an average team since week {h[0][0]}.",
                             "href": base + "#/team/" + ab})
    k0 = rows[0] if rows else None
    return {"phase": f"Week {idx.get('week')}", "status": f"{idx.get('season')} regular season · week {idx.get('week')}",
            "kpis": [{"label": "SB fav", "value": (teams.get(k0[0]) or {}).get("name", "—").split(" ")[-1] if k0 else "—",
                      "sub": f"{k0[1]['p_sb'] * 100:.0f}%" if k0 else None},
                     {"label": "Games", "value": len([g for g in idx.get("games") or []]), "sub": "this week"},
                     {"label": "Top QB", "value": surname(qbs[0]["name"]) if qbs else "—", "sub": qbs[0]["team"] if qbs else None}],
            "updated_at": idx.get("updated_at")}


# ───────────────────────────────────────────────────────────── NHL
def build_hockey(ctx: Ctx, base: str, out: dict):
    d = DOCS / "rink" / "data"
    idx = load(d / "index.json")
    if not idx:
        raise RuntimeError("index.json missing")
    pidx = load(d / "players_index.json") or {}
    teams = idx.get("teams") or {}

    def tm(a):
        t = teams.get(a) or {}
        return team(t.get("name", a).split(" ")[-1] if t.get("name") else a, a, t.get("colour"),
                    href=base + "#/team/" + a)

    seen, games = set(), []
    for g in (idx.get("live") or []) + (idx.get("today") or []) + (idx.get("recent") or []) + (idx.get("upcoming") or []):
        if g["game_id"] in seen:
            continue
        seen.add(g["game_id"])
        m, mk = g.get("model") or {}, g.get("market") or {}
        games.append(game("hockey", "NHL", g["game_id"], g.get("start"), g.get("status"), tm(g["home"]), tm(g["away"]),
                          g.get("hs"), g.get("as"), p_home=r4(m.get("p_home")), market_home=r4(mk.get("p_home")),
                          total=m.get("total"), period=g.get("period"), clock=g.get("clock"),
                          wp_home=r4(g.get("wp_home")), xg=[(g.get("xg") or {}).get("home"), (g.get("xg") or {}).get("away")] if g.get("xg") else None,
                          note=("OT" if g.get("ot") else None), href=base + "#/game/" + g["game_id"]))
        if norm_status(g.get("status")) == "pre":
            gr = gap_row("hockey", f"{tm(g['away'])['name']} @ {tm(g['home'])['name']}", m.get("p_home"),
                         mk.get("p_home"), base + "#/game/" + g["game_id"], detail="home win")
            if gr:
                out["gaps"].append(gr)
    out["games"].extend(pick_games(ctx, games, 5, 8))
    for gp in idx.get("gaps") or []:
        if gp.get("kind") == "game":
            continue
        nm = (teams.get(gp.get("team")) or {}).get("name", gp.get("team"))
        lab = {"playoffs": f"{nm} make the playoffs", "division": f"{nm} win the division",
               "presidents": f"{nm} win the Presidents' Trophy", "cup": f"{nm} win the Stanley Cup"}
        gr = gap_row("hockey", lab.get(gp["kind"], f"{nm}: {gp['kind']}"),
                     gp["model"], gp["market"], base + "#/markets", kind="futures")
        if gr:
            out["gaps"].append(gr)
    po = idx.get("playoff_odds") or {}
    rows = sorted(po.items(), key=lambda kv: -(kv[1].get("p_cup") or 0))[:8]
    out["futures"]["hockey"] = {"title": "Stanley Cup", "rows": [
        {"name": (teams.get(k) or {}).get("name", k), "abbr": k, "p": r4(v.get("p_cup")),
         "p2": r4(v.get("p_playoffs")), "colour": (teams.get(k) or {}).get("colour"),
         "href": base + "#/team/" + k} for k, v in rows]}
    season = load(d / str(idx.get("season")) / "season.json") or {}
    srows = (season.get("standings") or {}).get("rows") or []
    out["charts"]["nhl_xg"] = {"title": "Expected-goals share v points %", "href": base + "#/standings", "points": [
        {"name": r.get("name"), "abbr": r["team"], "x": r.get("xgf_pct"), "y": r.get("p_pct"), "gp": r.get("gp"),
         "colour": (teams.get(r["team"]) or {}).get("colour"), "href": base + "#/team/" + r["team"]}
        for r in srows if r.get("xgf_pct") is not None and r.get("p_pct") is not None]}
    lead = idx.get("leaders") or {}
    pts = []
    for pid, v in (lead.get("s_p") or [])[:8]:
        p = pidx.get(pid) or []
        pts.append({"name": p[0] if p else pid, "team": p[1] if len(p) > 1 else None, "value": v,
                    "colour": (teams.get(p[1]) or {}).get("colour") if len(p) > 1 else None,
                    "href": base + "#/player/" + pid})
    out["leaders"]["hockey"] = {"title": "Points", "unit": "pts", "rows": pts}
    gs = []
    for pid, v in (lead.get("g_gsax") or [])[:1]:
        p = pidx.get(pid) or []
        gs.append((p[0] if p else pid, p[1] if len(p) > 1 else None, v, pid))
    if gs:
        nm, tmab, v, pid = gs[0]
        out["stats"].append({"sport": "hockey", "kicker": "Best in net", "value": f"{v:+.1f}",
                             "unit": "goals saved above expected",
                             "text": f"{nm} ({tmab}) has saved {v:.1f} more goals than an average goalie would on "
                                     f"the same shots this season.", "href": base + "#/player/" + pid})
    for k, t in teams.items():
        out["search"].append(["hockey", t.get("name"), "NHL team · " + (t.get("division") or ""), base + "#/team/" + k])
    k0 = rows[0] if rows else None
    top = srows[0] if srows else None
    return {"phase": (idx.get("phase") or "").capitalize(),
            "status": f"{sum(1 for g in games if g['status'] == 'live')} live · {len(idx.get('upcoming') or [])} upcoming",
            "kpis": [{"label": "Cup fav", "value": (teams.get(k0[0]) or {}).get("name", "—").split(" ")[-1] if k0 else "—",
                      "sub": f"{k0[1]['p_cup'] * 100:.0f}%" if k0 else None},
                     {"label": "1st", "value": top["team"] if top else "—",
                      "sub": f"{top['pts']} pts" if top else None},
                     {"label": "Points", "value": surname(pts[0]["name"]) if pts else "—",
                      "sub": f"{pts[0]['value']} pts" if pts else None}],
            "updated_at": idx.get("updated_at")}


# ───────────────────────────────────────────────────────────── college (pending launch)
def build_college(ctx: Ctx, base: str, out: dict):
    """The Quant Campus: docs/campus/data/index.json (oddsmarkets/college/site.py) and its search.json."""
    d = DOCS / "campus" / "data"
    idx = load(d / "index.json")
    if not idx or not idx.get("levels"):
        raise RuntimeError("index.json missing")
    status, kpis = [], []
    phase_lab = {"preseason": "preseason", "regular": "regular season", "conf_champ": "championship week",
                 "bowls": "bowls", "playoff": "playoff", "offseason": "offseason", "conf_tourneys": "conference tournaments",
                 "ncaa": "NCAA tournament"}
    for L in ("cfb", "mbb", "wbb"):
        lg = (idx["levels"] or {}).get(L) or {}
        if not lg.get("ok"):
            continue
        teams = lg.get("teams") or {}
        LU = L.upper()
        S = lg.get("current_season")

        def tm(tid, rank=None):
            t = teams.get(str(tid)) or {}
            nm = t.get("short") or t.get("name") or str(tid)
            return team((f"#{rank} " if rank and rank <= 25 else "") + nm, t.get("abbr"), t.get("colour"),
                        href=base + "#/" + L + "/team/" + str(tid))

        seen, games = set(), []
        for g in (lg.get("today") or []) + (lg.get("next_games") or []) + (lg.get("last_games") or []):
            if g.get("id") in seen:
                continue
            seen.add(g.get("id"))
            m, mk = g.get("model") or {}, g.get("market") or {}
            note = g.get("round") if g.get("stype") in ("cfp", "ncaa", "bowl") else None
            href = base + "#/" + L + "/game/" + str(g["id"]) + ("" if g.get("season") in (None, S) else f"?season={g['season']}")
            games.append(game("college", LU, g["id"], g.get("date"), g.get("status"), tm(g["home"], g.get("hr")),
                              tm(g["away"], g.get("ar")), g.get("hs"), g.get("as"), p_home=r4(m.get("p_home")),
                              market_home=r4(mk.get("p_home")), spread=mk.get("spread_home"), total=m.get("total"),
                              note=note, href=href))
            if norm_status(g.get("status")) == "pre":
                gr = gap_row("college", f"{tm(g['away'])['name']} @ {tm(g['home'])['name']} ({LU})",
                             m.get("p_home"), mk.get("p_home"), href, detail="home win")
                if gr:
                    out["gaps"].append(gr)
        out["games"].extend(pick_games(ctx, games, 4, 6))
        rows = [r for r in (lg.get("title_odds") or []) if r.get("p")][:8]
        if rows:
            out["futures"]["college" if L == "cfb" else "college_" + L] = {
                "title": f"{LU} national title", "rows": [
                    {"name": (teams.get(r["team"]) or {}).get("name") or r["team"], "abbr": (teams.get(r["team"]) or {}).get("abbr"),
                     "p": r4(r["p"]), "market": r4(r.get("market")), "colour": (teams.get(r["team"]) or {}).get("colour"),
                     "href": base + "#/" + L + "/team/" + r["team"]} for r in rows]}
            t0 = teams.get(rows[0]["team"]) or {}
            kpis.append({"label": f"{LU} fav", "value": t0.get("short") or t0.get("name") or rows[0]["team"],
                         "sub": f"{(rows[0]['p'] or 0) * 100:.0f}% title"})
        status.append(f"{LU} {phase_lab.get(lg.get('phase'), lg.get('phase') or '')}".strip())
    srch = load(d / "search.json") or []
    for r in srch if isinstance(srch, list) else []:
        if r.get("t") and r.get("href"):
            out["search"].append(["college", r["t"], r.get("s") or "", base + r["href"]])
    return {"phase": " · ".join(status), "status": " · ".join(status), "kpis": kpis[:3], "updated_at": idx.get("updated_at")}


BUILDERS = {"football": build_football, "f1": build_f1, "basketball": build_basketball, "tennis": build_tennis,
            "baseball": build_baseball, "nfl": build_nfl, "hockey": build_hockey, "college": build_college}


def football_search(base: str, out: dict):
    d = DOCS / "site" / "data"
    ci = load(d / "clubs_index.json") or {}
    f = ci.get("fields") or []
    for row in ci.get("rows") or []:
        r = dict(zip(f, row))
        out["search"].append(["football", r.get("name"), ("National team" if r.get("national") else "Club")
                              + (" · " + r["country"] if r.get("country") else ""),
                              base + "#/club/" + str(r.get("id"))])
    comps = load(d / "competitions.json") or {}
    for c in comps.get("competitions", []):
        out["search"].append(["football", c.get("name"), "Competition · " + (c.get("country") or ""),
                              base + "#/" + c["slug"]])


def copy_kit():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from design_kit import copy_kit as _copy
    _copy(OUT)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--links", choices=["public", "local"], default="public")
    ap.add_argument("--no-kit", action="store_true", help="do not copy docs/_design into docs/home/assets/qk")
    ap.add_argument("--with-pending", action="store_true",
                    help="include sites not launched yet (PENDING, e.g. The Quant Campus) for local preview")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ctx = Ctx(a.links, now)
    out = {"games": [], "gaps": [], "futures": {}, "leaders": {}, "charts": {}, "stats": [], "search": []}
    sports = []
    for key, folder, repo, label, site in SPORTS + [x for x in PENDING if x[0] in LAUNCHED or a.with_pending]:
        base = ctx.base(folder, repo)
        entry = {"key": key, "label": label, "site": site, "url": base, "data": PUBLIC.format(repo) + "data/",
                 "ok": False}
        part = {"games": [], "gaps": [], "futures": {}, "leaders": {}, "charts": {}, "stats": [], "search": []}
        try:
            entry.update(BUILDERS[key](ctx, base, part))
            if key == "football":
                football_search(base, part)
        except Exception as exc:  # one sport failing never takes the others down
            log(f"{key}: skipped ({exc!r})")
        else:
            entry["ok"] = True
            for k, v in part.items():
                if isinstance(v, list):
                    out[k].extend(v)
                else:
                    out[k].update(v)
        sports.append(entry)
    # Biggest model-v-market disagreements, at most four per sport so one busy market
    # (NHL playoff futures, say) cannot fill the whole chart.
    per, gaps = {}, []
    for g in sorted([g for g in out["gaps"] if abs(g["diff"]) >= 0.03], key=lambda g: -abs(g["diff"])):
        if per.get(g["sport"], 0) < 4:
            per[g["sport"]] = per.get(g["sport"], 0) + 1
            gaps.append(g)
    out["gaps"] = gaps[:20]
    out["games"].sort(key=lambda g: ({"live": 0, "pre": 1, "final": 2}[g["status"]], g["start"] or ""))
    search = out.pop("search")
    home = {"version": 1, "updated_at": iso(now), "links": a.links, "sports": sports, **out}
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    with open(OUT / "data" / "home.json", "w", encoding="utf-8") as fh:
        json.dump(home, fh, ensure_ascii=False, separators=(",", ":"))
    with open(OUT / "data" / "search.json", "w", encoding="utf-8") as fh:
        json.dump({"fields": ["sport", "name", "sub", "href"], "rows": [s for s in search if s[1]]},
                  fh, ensure_ascii=False, separators=(",", ":"))
    if not a.no_kit:
        copy_kit()
    sz = (OUT / "data" / "home.json").stat().st_size
    log(f"home.json {sz / 1024:.0f} KB · {len(out['games'])} games · {len(out['gaps'])} gaps · "
        f"{sum(1 for s in sports if s['ok'])}/{len(sports)} sports · {len(search)} search rows")


if __name__ == "__main__":
    main()
