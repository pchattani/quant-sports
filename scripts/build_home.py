"""Build The Quant Sports home page data (docs/home/data/home.json + search.json) and copy the design kit.

The home page (docs/home/) is a static page in the shared design system. It reads one compact,
normalised file written here from the sport sites' already-built data trees:

    docs/site/data      football   (hub.json, competitions.json, <comp>/probs.json)
    docs/paddock/data   F1         (index.json, markets.json for our next-race model, <year>/season.json)
    docs/hardwood/data  NBA/WNBA   (index.json, <league>/<season>/season.json)
    docs/ace/data       tennis     (index.json)
    docs/bullpen/data   MLB        (index.json, players_index.json)
    docs/gridiron/data  NFL        (index.json, <season>/season.json, players_index.json)
    docs/rink/data      NHL        (index.json, <season>/season.json, players_index.json)
    docs/campus/data    college    (index.json, search.json)

Nothing is fetched from the network. Every sport is optional: a missing or broken tree is
logged and skipped, so the home page still builds with the sports that are present.

Live scores: the page refreshes scores in the browser from each sport's published index.json
(GitHub Pages sends Access-Control-Allow-Origin: *), so home.json only has to be as fresh as
the last build. See docs/_design/README.md.

Usage:
    python scripts/build_home.py                  # links point at the public GitHub Pages sites
    python scripts/build_home.py --links local    # links point at ../site/, ../paddock/ ... (preview)
    python scripts/build_home.py --links local --with-pending   # also the sites not launched yet (local preview)
    python scripts/build_home.py --links local --now 2026-10-17T23:00:00Z   # preview an older local snapshot

Matchday copy (kit v3, docs/_design/MIGRATION_V3.md), all added fields:
    games[].why          one friendly line on why a game is worth watching (our numbers only, never the market)
    leaders[k].hot       { title, expl } for the home page's "Who's hot" card: what the name leads, what it means
    calibration          { hockey | basketball | nfl | baseball: { league, span, n, brier, subject, unit, bins } }
    stats[].title/note   a plain headline for the stat of the day and an "i" note on what the number means
                         for "How sure are we?", read from each site's calibration.json

Top of the page (added fields; the significance rule is oddsmarkets/common/featured.py, the week's numbers
oddsmarkets/common/digest.py, both shared with the sport overviews):
    games[].weight       the game's significance score (upcoming and live games only): "N games. Our calls." ranks by it
    featured             { today: [{ key: "<sport>:<id>", score, reasons }], week: { key, score, reasons } | null }:
                         the game of the day, best first (the front end takes the first still upcoming or live at
                         the viewer's clock), and the biggest occasion of the week as the fallback
    digest               { record, upset, swing, record_sports, left_out }: our favourites over the past 7 days
                         (only finished games with a chance published before the start), the week's biggest upset,
                         and the biggest move in a title chance (football's title-chance history, F1's per-round
                         title history where built)
    sports[].topline     { stage, next: { title, start, href, league } }: one line per sport on where its season is
                         and its most significant game or event in the next 7 days

Round 6 (the hub experience; the market quiet beside ours; our record off the page):
    games[].market_home  the market's chance for the home side (player 1 in tennis), before the start only, and
    games[].market_src   its source keys ('kalshi', 'polymarket', 'draftkings', 'espn'): the page shows "Market 54%"
                         small and grey beside our chance (STYLE_GUIDE §3); football has no per-match market here
    stories              { surprises: [{ sport, league, what, name, short, abbr, colour, href, from, to, since, until,
                         delta }] (the season's biggest movers in a playoff chance, from each site's race_log.json, at
                         most one riser and one faller per league, four in all), hot: [{ sport, league, name, abbr,
                         colour, href, w, l, d, gp, margin, players }] (each site digest's team of the week, best first) }
    digest.record and calibration stay in the payload; the page no longer shows them (they live on the Model pages).

Sites not launched yet (PENDING, e.g. The Quant Campus) are left out of home.json and search.json unless their key
is in LAUNCHED or --with-pending is given, so the live home page never links a Pages site that does not exist.
The kit hides them the same way (QK.SPORTS drops `pending` entries outside local preview).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from oddsmarkets.common import digest as DG      # noqa: E402  the week's record, upset, swing (shared with overviews)
from oddsmarkets.common import featured as FT    # noqa: E402  the significance rule: which game leads the page

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
STALE_HOURS = 6   # a sport whose input is older than this is flagged stale in home.json

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
        # A "live" game that started longer ago than any game lasts, or a "pre" game well past its start, comes from
        # a stale input (a site that has not rebuilt, a source outage): it is left off rather than shown as live.
        self.live_max = timedelta(hours=8)
        self.pre_grace = timedelta(hours=3)

    def base(self, folder: str, repo: str) -> str:
        return f"../{folder}/" if self.links == "local" else PUBLIC.format(repo)


TWO_WORD = ("Maple Leafs", "Red Wings", "Golden Knights", "Blue Jackets", "Blue Jays", "Red Sox", "White Sox",
            "Trail Blazers")


def nickname(full):
    """'Vegas Golden Knights' -> 'Golden Knights', 'Colorado Avalanche' -> 'Avalanche' (US-league team names)."""
    full = str(full or "")
    for two in TWO_WORD:
        if full.endswith(two):
            return two
    return full.split(" ")[-1] if full else full


def team(name, abbr=None, colour=None, logo=None, href=None, full=None, alt=None):
    """A team for home.json. full (the full name, 'Winnipeg Jets') lets the Broadcast hero print the city under the
    nickname; alt (the second kit colour) is the hero's fallback when the two teams' colours clash."""
    t = {"name": name}
    if abbr:
        t["abbr"] = abbr
    if colour:
        t["colour"] = colour
    if full and full != name:
        t["full"] = full
    if alt:
        t["alt"] = alt
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


def mkt(g, key="p_home"):
    """The quiet market for a game (round 6): {market_home, market_src} from a site's payload game, before the start
    only, else {}. The Home page shows it small and grey beside our chance (STYLE_GUIDE §3); the source keys are kept
    short ('kalshi', 'polymarket', 'draftkings', 'espn') and the kit makes them readable."""
    m = g.get("market") if isinstance(g.get("market"), dict) else {}
    p = m.get(key)
    if p is None or norm_status(g.get("status")) != "pre":
        return {}
    src = m.get("sources") or m.get("source") or m.get("src") or []
    if not isinstance(src, list):
        src = [src]
    names = []
    for x in src:
        k = (x.get("source") if isinstance(x, dict) else x) or ""
        k = str(k).lower().split("_")[0]
        if k and k not in names:
            names.append(k)
    return {"market_home": r4(p), "market_src": names or None}


def race_moves(out: dict, ctx, sport: str, league: str, log, metric: str, tm, what: str):
    """Every team's move in one race-log metric over the season so far ({day: {key: p}}, oddsmarkets/common/league.py
    race logs): the first snapshot against the latest at or before ctx.now (no look-ahead). Candidates for the Home
    page's "Biggest surprises" go to out["races"]. Skipped when the log is too short, stale, or the race is settled."""
    snaps = {d: v for d, v in ((log or {}).get(metric) or {}).items() if isinstance(v, dict) and not str(d).startswith("_")}
    days = sorted(d for d in snaps if parse_ts(d) and parse_ts(d) <= ctx.now)
    if len(days) < 2:
        return
    d0, d1 = days[0], days[-1]
    if (parse_ts(d1) - parse_ts(d0)).days < 7 or (ctx.now - parse_ts(d1)).days > 10:
        return
    last = {k: v for k, v in snaps[d1].items() if isinstance(v, (int, float))}
    if sum(1 for v in last.values() if 0.02 < v < 0.98) < max(3, 0.3 * len(last)):
        return                                          # the race is all but settled: no story in it
    for k, p1 in last.items():
        p0 = snaps[d0].get(k)
        if not isinstance(p0, (int, float)):
            continue
        t = tm(k)
        out["races"].append({"sport": sport, "league": league, "what": what, "name": t.get("full") or t.get("name"),
                             "short": t.get("name"), "abbr": t.get("abbr"), "colour": t.get("colour"), "href": t.get("href"),
                             "from": round(float(p0), 3), "to": round(float(p1), 3), "since": d0, "until": d1,
                             "delta": round(float(p1) - float(p0), 3)})


def race_log(path: Path, season):
    log = load(path) or {}
    if season is not None and str(season) in log:
        return log[str(season)]
    return log[sorted(log)[-1]] if log else None


def hot_team(out: dict, sport: str, league: str, hot, t: dict, players: bool = False):
    """The site digest's team (or player) of the week as a Home candidate: {w, l, d, gp, margin} plus the team."""
    if not isinstance(hot, dict) or not hot.get("gp"):
        return
    out["hot_teams"].append({"sport": sport, "league": league, "name": t.get("full") or t.get("name"),
                             "short": t.get("name"), "abbr": t.get("abbr"), "colour": t.get("colour"), "href": t.get("href"),
                             "w": hot.get("w") or 0, "l": hot.get("l") or 0, "d": hot.get("d") or 0, "gp": hot.get("gp"),
                             "margin": hot.get("margin"), "players": players or None})


def fan_stories(races, hots):
    """The Home page's fan stories (round 6): `surprises` (the season's biggest movers in a playoff chance, at most
    one per sport, risers and fallers) and `hot` (each sport's team of the week, best first)."""
    by_sport = {}
    for r in sorted(races or [], key=lambda r: -abs(r["delta"])):
        if abs(r["delta"]) < 0.15:
            break
        key = (r["sport"], r["league"])
        by_sport.setdefault(key, [])
        sign = r["delta"] > 0
        if len(by_sport[key]) < 2 and all((x["delta"] > 0) != sign for x in by_sport[key]):
            by_sport[key].append(r)
    firsts = sorted((v[0] for v in by_sport.values()), key=lambda r: -abs(r["delta"]))
    seconds = sorted((v[1] for v in by_sport.values() if len(v) > 1), key=lambda r: -abs(r["delta"]))
    surprises = (firsts + seconds)[:4]
    hot = sorted((h for h in hots or [] if (h.get("gp") or 0) >= 2),
                 key=lambda h: (-(h["w"] - h["l"]), -(h["w"] / max(1, h["gp"])), -(h.get("margin") or 0)))
    return {"surprises": surprises, "hot": hot[:6]}


def in_window(ctx: Ctx, g) -> bool:
    d = parse_ts(g.get("start"))
    if g["status"] == "live":
        return d is None or ctx.now - ctx.live_max <= d <= ctx.now + ctx.pre_grace
    if g["status"] == "pre":
        return d is not None and ctx.now - ctx.pre_grace <= d <= ctx.hi
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

    def tid_of(p, tid=None):
        if tid:
            return str(tid)
        if p and "/crests/" in p:
            return p.rsplit("/", 1)[-1].split(".")[0]
        return None

    def club_href(tid, slug):
        return base + "#/club/" + tid + "?c=" + slug if tid else None

    # Kit colours by club id (clubs_index.json `colour`, `alt`; none for a club without a crest or a national team,
    # and the kit falls back to cobalt v slate)
    ci = load(d / "clubs_index.json") or {}
    kit = {}
    for row in ci.get("rows") or []:
        r = dict(zip(ci.get("fields") or [], row))          # a row without colours stops at "comps"
        if r.get("colour"):
            kit[str(r.get("id"))] = (r["colour"], r.get("alt"))

    def side(name, p, tid, slug):
        t = tid_of(p, tid)
        colour, alt = kit.get(t) or (None, None)
        return team(name, colour=colour, alt=alt, logo=crest(p), href=club_href(t, slug))

    # our title chances per big league, for the significance score's stakes (a title chance in play)
    title_p = {}
    for slug in TITLE_LEAGUES:
        pr = load(d / slug / "probs.json") or {}
        title_p[slug] = {t.get("team"): t.get("p_title") for t in pr.get("teams") or [] if t.get("team")}

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
                     side(m["home"], cr[0], m.get("home_id"), m["comp"]),
                     side(m["away"], cr[1], m.get("away_id"), m["comp"]),
                     m.get("hs"), m.get("as"),
                     p_home=r4(mod.get("h")), p_draw=r4(mod.get("d")), p_away=r4(mod.get("a")),
                     xg=m.get("xg"), href=base + "#/" + m["comp"] + "/match/" + str(m["id"]),
                     note=(str(m.get("round")).upper() if isinstance(m.get("round"), str) else
                           ("Round " + str(m["round"]) if m.get("round") else None)),
                     rank=pri.get(m["comp"], 99), comp=m["comp"])
            rnd = m.get("round") if isinstance(m.get("round"), str) else None
            stage = FT.stage_of({"sig": {"round": rnd}}) or ("knockout" if m.get("stage") == "playoff" else None)
            tp = title_p.get(m["comp"])
            g["sig"] = {"comp": m["comp"], "stage": stage,
                        "title": [tp.get(m["home"]) or 0.0, tp.get(m["away"]) or 0.0] if tp else None,
                        "rivalry": FT.RIVALRIES.get(frozenset((m["home"], m["away"])))}
            games.append(g)
    picked = pick_games(ctx, games, n_final=8, n_pre=14,
                        key=lambda g: (g.get("rank", 99), g["start"]))
    for g in games:
        g.pop("rank", None)
    out["games"].extend(picked)
    out["pool"].extend(games)

    # Title races: our chance per big league (the market never reaches the home page, STYLE_GUIDE §3)
    titles = []
    for slug in TITLE_LEAGUES:
        probs = load(d / slug / "probs.json")
        if not probs:
            continue
        rows = []
        ids = {k: (v or {}).get("team_id") for k, v in ((load(d / slug / "teams.json") or {}).get("teams") or {}).items()
               if isinstance(v, dict)}
        for t in sorted(probs.get("teams", []), key=lambda t: -(t.get("p_title") or 0))[:6]:
            row = {"name": t["team"], "p": r4(t.get("p_title")), "exp_pts": t.get("exp_pts")}
            colour = (kit.get(str(ids.get(t["team"]))) or (None, None))[0]
            if colour:
                row["colour"] = colour
            rows.append(row)
        titles.append({"league": comp_names.get(slug, slug), "slug": slug, "rows": rows,
                       "href": base + "#/" + slug + "/probs"})
        snaps = (load(d / slug / "history.json") or {}).get("snapshots") or []
        for r in rows[:4]:
            pts = [[sn.get("ts"), (sn.get("title") or {}).get(r["name"])] for sn in snaps
                   if (sn.get("title") or {}).get(r["name"]) is not None]
            if len(pts) > 1:
                out["series"].append({"sport": "football", "name": r["name"], "league": comp_names.get(slug, slug),
                                      "kind": "title", "points": pts, "href": base + "#/" + slug + "/probs"})
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

    n_live = sum(1 for g in games if g["status"] == "live" and in_window(ctx, g))
    today = iso(ctx.now)[:10]
    n_today = sum(1 for g in games if (g["start"] or "")[:10] == today)
    top = goals[0] if goals else None
    n_comps = len({g["comp"] for g in games if (g["start"] or "")[:10] == today})
    sp = {"phase": "In season", "status": f"{n_today} matches today" + (f" · {n_live} live" if n_live else ""),
          "stage": (f"{n_today} matches today in {n_comps} competitions" if n_today else
                    f"{len(comps.get('competitions', []))} competitions followed"),
          "kpis": [{"label": "Comps", "value": len(comps.get("competitions", []))},
                   {"label": "Today", "value": n_today, "sub": "matches"},
                   {"label": "Top scorer", "value": surname(top["name"]) if top else "—",
                    "sub": f"{top['value']} goals" if top else None}],
          "updated_at": hub.get("updated_at")}
    if top and top.get("xg"):
        out["stats"].append({"sport": "football", "kicker": "Finishing above the model",
                             "title": f"{surname(top['name'])} keeps beating the model",
                             "note": "<b>Expected goals</b> rate every shot by how often that kind of chance goes in. "
                                     "Scoring more than them means finishing better than the average shooter.",
                             "value": f"+{top['value'] - top['xg']:.1f}",
                             "unit": "goals over xG",
                             "text": f"{top['name']} has {top['value']} goals from {top['xg']:.1f} expected goals "
                                     f"for {top['team']} this season.",
                             "href": top["href"]})
    if titles:
        t0 = titles[0]
        if t0["rows"] and t0["rows"][0].get("p"):
            r0 = t0["rows"][0]
            out["stats"].append({"sport": "football", "kicker": f"{t0['league']} title",
                                 "title": f"{r0['name']} lead the {t0['league']} race",
                                 "note": "<b>Our title chance</b> plays out the rest of the season thousands of times "
                                         "with our match forecasts and counts how often each club finishes first.",
                                 "value": f"{r0['p'] * 100:.0f}%", "unit": "our title chance",
                                 "text": f"We make {r0['name']} {r0['p'] * 100:.0f}% to win the {t0['league']}, "
                                         f"from thousands of simulated seasons.",
                                 "href": t0["href"]})
    if goals:
        g0 = goals[0]
        nxt = goals[1] if len(goals) > 1 else None
        better = g0.get("xg") is not None and g0["value"] > g0["xg"]
        out["leaders"]["football"]["hot"] = {
            "title": "Most goals" + (f", {g0['league']}" if g0.get("league") else ""),
            "expl": (f"{g0['value']} goals from chances worth {g0['xg']:.1f}: "
                     + ("finishing better than the average shooter." if better else "the chances say more should have gone in."))
            if g0.get("xg") is not None else "Goals in all competitions this season."}
    return sp


# ───────────────────────────────────────────────────────────── F1
def build_f1(ctx: Ctx, base: str, out: dict):
    d = DOCS / "paddock" / "data"
    idx = load(d / "index.json")
    if not idx:
        raise RuntimeError("index.json missing")
    mk = load(d / "markets.json") or {}   # our next-race model only; its prices never reach the home page
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
        field = sorted(model, key=lambda k: -(model.get(k) or 0))[:8]
        race = {"name": nx.get("name"), "round": nx.get("round"), "year": nx.get("year"),
                "date": nx.get("date"), "circuit": (nx.get("circuit") or {}).get("name"),
                "locality": (nx.get("circuit") or {}).get("locality"),
                "country": (nx.get("circuit") or {}).get("country"),
                "sessions": nx.get("sessions"),
                "href": base + "#/race/" + str(nx.get("year")) + "/" + str(nx.get("round")),
                "field": [{"name": dname(k), "code": (drivers.get(k) or {}).get("code"), "colour": dcol(k),
                           "p": r4(model.get(k)),
                           "href": base + "#/driver/" + k} for k in field]}
        sess = nx.get("sessions") or {}
        gp = game("f1", "Formula 1", f"{nx.get('year')}-{nx.get('round')}",
                  sess.get("race") or nx.get("date"), "pre",
                  team(nx.get("name") or "Grand Prix"), team((nx.get("circuit") or {}).get("name") or ""),
                  href=race["href"], note=f"Round {nx.get('round')}", event=True,
                  fav=race["field"][0]["name"] if race["field"] else None,
                  fav_p=race["field"][0]["p"] if race["field"] else None)
        n_rounds = ((idx.get("seasons_meta") or {}).get(str(year)) or {}).get("rounds")
        gp["sig"] = {"stage": "final" if n_rounds and nx.get("round") == n_rounds else None}
        out["games"].append(gp)
        out["pool"].append(gp)
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
    # the drivers' title chance after each round (season.json title_history, where the build has written it)
    hist = [h for h in season.get("title_history") or [] if isinstance(h, dict) and h.get("as_of")]
    for k, _v in title[:4]:
        pts = [[h["as_of"], ((h.get("drivers") or {}).get(k) or {}).get("p_title")] for h in hist
               if ((h.get("drivers") or {}).get(k) or {}).get("p_title") is not None]
        if len(pts) > 1:
            out["series"].append({"sport": "f1", "name": dname(k), "league": "F1 drivers' title", "kind": "title",
                                  "points": pts, "href": base + "#/season/" + str(year)})
    out["futures"]["f1"] = {"title": "Drivers' title", "rows": [
        {"name": dname(k), "p": r4(v.get("p_title")),
         "colour": dcol(k), "href": base + "#/driver/" + k} for k, v in title]}

    last = idx.get("last") or {}
    leader = st[0] if st else None
    second = st[1] if len(st) > 1 else None
    meta = (idx.get("seasons_meta") or {}).get(str(year)) or {}
    sp = {"phase": f"Round {meta.get('completed', '?')} of {meta.get('rounds', '?')}",
          "stage": (f"{meta.get('completed')} of {meta.get('rounds')} rounds run" if meta.get("rounds") else None)
          if meta.get("completed") != meta.get("rounds") else "Season complete",
          "status": (f"Next: {nx.get('name')} · {nice_date(nx.get('date'))}" if nx else "Season complete"),
          "kpis": [{"label": "Leader", "value": surname(dname(leader["driver"])) if leader else "—",
                    "sub": f"{leader['points']:.0f} pts" if leader else None},
                   {"label": "Gap to P2", "value": f"{leader['points'] - second['points']:.0f}" if leader and second else "—",
                    "sub": "points"},
                   {"label": "Last win", "value": surname(dname(last.get("winner"))) if last.get("winner") else "—",
                    "sub": (last.get("name") or "").replace(" Grand Prix", " GP")}],
          "updated_at": idx.get("updated_at")}
    if leader and second and title:
        gap = leader['points'] - second['points']
        out["stats"].append({"sport": "f1", "kicker": "Championship lead",
                             "title": f"{surname(dname(leader['driver']))} is " + ("out of sight" if gap >= 50 else "in front"),
                             "note": "A win is worth 25 points, so every 25 clear is a race the rest need back.",
                             "value": f"{leader['points'] - second['points']:.0f}", "unit": "points clear",
                             "text": f"{dname(leader['driver'])} leads by {leader['points'] - second['points']:.0f} "
                                     f"points with {meta.get('rounds', 0) - meta.get('completed', 0)} rounds left; "
                                     f"our title chance {pct_text(title[0][1].get('p_title'))}.",
                             "href": base + "#/season/" + str(year)})
    lead_rows = [{"name": dname(r["driver"]), "team": (teams.get(r.get("team")) or {}).get("name"),
                  "value": r.get("points"), "sub": f"{r.get('wins', 0)} wins", "colour": dcol(r["driver"]),
                  "href": base + "#/driver/" + r["driver"]} for r in st[:10]]
    out["leaders"]["f1"] = {"title": "Drivers' points", "unit": "pts", "rows": lead_rows}
    if leader and second:
        left = meta.get("rounds", 0) - meta.get("completed", 0)
        out["leaders"]["f1"]["hot"] = {"title": "Drivers' points",
                                       "expl": f"{leader['points'] - second['points']:.0f} points clear with {left} "
                                               f"race{'s' if left != 1 else ''} left."}
    for k, v in drivers.items():
        out["search"].append(["f1", v.get("name"), "Driver · " + ((teams.get(v.get("team")) or {}).get("name") or ""),
                              base + "#/driver/" + k])
    for k, v in teams.items():
        out["search"].append(["f1", v.get("name"), "Constructor", base + "#/team/" + k])
    return sp


PHASE_WORD = {"pre": "preseason", "preseason": "preseason", "regular": "regular season", "reg": "regular season",
              "post": "playoffs", "playoffs": "playoffs", "postseason": "postseason", "off": "offseason",
              "offseason": "offseason"}


# ───────────────────────────────────────────────────────────── basketball
def build_basketball(ctx: Ctx, base: str, out: dict):
    d = DOCS / "hardwood" / "data"
    idx = load(d / "index.json")
    if not idx:
        raise RuntimeError("index.json missing")
    sp_status, kpis, stages = [], [], []
    futures = {}
    for L, lg in (idx.get("leagues") or {}).items():
        teams = lg.get("teams") or {}
        LU = L.upper()
        season = load(d / L / str(lg.get("current_season")) / "season.json") or {}
        sim = (season.get("sim") or {}).get("teams") or {}

        def tm(tid):
            t = teams.get(str(tid)) or {}
            return team(t.get("short") or t.get("name") or str(tid), t.get("abbr"), t.get("colour"),
                        href=base + "#/" + L + "/team/" + str(tid), full=t.get("name"), alt=t.get("alt"))

        seen, games = set(), []
        for g in (lg.get("today") or []) + (lg.get("next_games") or []) + (lg.get("last_games") or []):
            if g["id"] in seen:
                continue
            seen.add(g["id"])
            m = g.get("model") or {}
            ser = g.get("series") or {}
            note = ser.get("round") and (ser["round"] + (f" · G{ser['game']}" if ser.get("game") else ""))
            x = game("basketball", LU, g["id"], g["date"], g["status"], tm(g["home"]), tm(g["away"]),
                     g.get("hs"), g.get("as"), p_home=r4(m.get("p_home")), **mkt(g),
                     total=m.get("total"), clock=g.get("clock"),
                     period=g.get("period"), wp_home=r4(g.get("wp_home")), note=note,
                     href=base + "#/" + L + "/game/" + str(g["id"]))
            rnd = str(ser.get("round") or "")
            x["sig"] = {"preseason": g.get("stype") == "pre",
                        "stage": "final" if "Finals" in rnd and "Conference" not in rnd else
                                 "semi" if "Conference Finals" in rnd or "Semifinal" in rnd else
                                 "playoff" if g.get("stype") == "post" else None,
                        "series": {"game": ser.get("game"), "best_of": 7 if L == "nba" else 5} if ser.get("game") else None,
                        "title": [(sim.get(str(g["home"])) or {}).get("p_title"),
                                  (sim.get(str(g["away"])) or {}).get("p_title")] if sim else None}
            games.append(x)
        out["games"].extend(pick_games(ctx, games, 4, 6))
        out["pool"].extend(games)
        race_moves(out, ctx, "basketball", LU, race_log(d / L / "race_log.json", lg.get("current_season")), "p_playoffs", tm, "playoff chance")
        hot_team(out, "basketball", LU, (lg.get("digest") or {}).get("hot"), tm((((lg.get("digest") or {}).get("hot")) or {}).get("key")))
        rows = sorted(sim.items(), key=lambda kv: -(kv[1].get("p_title") or 0))
        rows = [(k, v) for k, v in rows if (v.get("p_title") or 0) > 0][:8]
        if rows:
            futures[L] = {"title": f"{LU} title", "rows": [
                {"name": (teams.get(k) or {}).get("name") or k, "abbr": (teams.get(k) or {}).get("abbr"),
                 "p": r4(v.get("p_title")), "colour": (teams.get(k) or {}).get("colour"),
                 "href": base + "#/" + L + "/team/" + k} for k, v in rows]}
        sp_status.append(f"{LU} {lg.get('phase')}")
        live_rnd = next((str((g.get("series") or {}).get("round")) for g in (lg.get("today") or []) + (lg.get("next_games") or [])
                         if (g.get("series") or {}).get("round")), None)
        ph = str(lg.get("phase") or "")
        stages.append(live_rnd if live_rnd and live_rnd.startswith(LU) else LU + " " + (live_rnd or PHASE_WORD.get(ph, ph)))
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
            "stage": " · ".join(stages), "updated_at": idx.get("updated_at")}


# ───────────────────────────────────────────────────────────── tennis
TENNIS_LEVEL = {"slam": "Grand Slam", "finals": "Tour Finals", "m1000": "1000", "500": "500", "250": "250"}


def build_tennis(ctx: Ctx, base: str, out: dict):
    d = DOCS / "ace" / "data"
    idx = load(d / "index.json")
    if not idx:
        raise RuntimeError("index.json missing")
    kpis, status, stages = [], [], []
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
            mod = m.get("model") or {}
            e = ev.get(m.get("event")) or {}
            start = m.get("date")
            if start and len(start) == 16:
                start += ":00Z"
            g = game("tennis", f"{TU} · {e.get('name') or m.get('event')}", m["id"], start, m.get("status"),
                     team(n[0], href=base + "#/" + T + "/player/" + str(m.get("p1"))),
                     team(n[1], href=base + "#/" + T + "/player/" + str(m.get("p2"))),
                     hs, as_, p_home=r4(mod.get("p1")), **mkt(m, "p1"),
                     sets=[[s[0], s[1]] for s in sets if s[0] is not None] if sets else None,
                     note=m.get("round"), href=base + "#/" + T + "/match/" + str(m["id"]), players=True,
                     tba=True if (m.get("tba") or (start and len(start) == 10)) else None)   # date-only start
            # the event's level (slam, finals, m1000, 500, 250, other) where the index lists the event; an event it
            # does not list scores at the default (a minor event)
            g["sig"] = {"comp": e.get("level") or ("challenger" if "challenger" in str(m.get("event") or "") else None),
                        "round": m.get("round")}
            if g.get("tba"):
                g["sig"]["comp"] = g["sig"]["comp"] or "other"
            games.append(g)
        out["games"].extend(pick_games(ctx, games, 3, 5))
        out["pool"].extend(games)
        th = (tour.get("digest") or {}).get("hot") or {}
        if th.get("key") and names.get(th["key"]):
            hot_team(out, "tennis", TU, th, team(names.get(th["key"]) or str(th["key"]), href=base + "#/" + T + "/player/" + str(th["key"])), players=True)
        elo = (tour.get("elo_top") or {}).get("all") or []
        out["leaders"]["tennis_" + T] = {"title": f"{TU} Elo", "unit": "Elo", "rows": [
            {"name": names.get(p[0]) or p[0], "value": round(p[1]), "href": base + "#/" + T + "/player/" + p[0]}
            for p in elo[:10]],
            "hot": {"title": f"Top rated, {TU} (Elo)",
                    "expl": "Elo rating: beat a stronger player, gain more. 2,000 and up is rare air."}}
        if elo:
            kpis.append({"label": f"{TU} Elo 1", "value": surname(names.get(elo[0][0]) or elo[0][0]),
                         "sub": f"{elo[0][1]:.0f}"})
        for e in tour.get("events_now") or []:
            status.append(e.get("name"))
            lv = TENNIS_LEVEL.get(str(e.get("level")))
            stages.append(f"{TU}: {e.get('name')}" + (f" ({lv})" if lv else ""))
        for pid, nm in names.items():
            out["search"].append(["tennis", nm, f"{TU} player", base + "#/" + T + "/player/" + pid])
    if len(kpis) < 3:
        kpis.append({"label": "Events", "value": len(status), "sub": "in play"})
    return {"phase": "In season", "status": " · ".join(status) or "Between events", "kpis": kpis,
            "stage": " · ".join(stages) or "Between events", "updated_at": idx.get("updated_at")}


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
                    href=base + "#/mlb/team/" + str(tid), full=t.get("name"), alt=t.get("alt"))

    ps = idx.get("postseason") or {}
    p_ws = {k: v.get("p_ws") for k, v in (ps.get("teams") or {}).items()}
    open_series = {frozenset(map(str, s.get("teams") or [])): s for s in ps.get("series") or [] if not s.get("done")}
    seen, games = set(), []
    for g in (idx.get("today") or []) + (idx.get("recent") or []) + (idx.get("upcoming") or []):
        if g["gpk"] in seen:
            continue
        seen.add(g["gpk"])
        m = g.get("model") or {}
        ser = g.get("series") or {}
        note = ser.get("desc") and (ser["desc"].replace("Championship Series", "CS").replace("Division Series", "DS")
                                    + (f" · G{ser['game']}" if ser.get("game") else ""))
        x = game("baseball", "MLB", g["gpk"], g.get("start"), g.get("status"), tm(g["home"]), tm(g["away"]),
                 g.get("hs"), g.get("as"), p_home=r4(m.get("p_home")), **mkt(g),
                 total=m.get("total"), period=g.get("inning"), wp_home=r4(g.get("wp_home")), note=note,
                 href=base + "#/mlb/game/" + str(g["gpk"]))
        os_ = open_series.get(frozenset((str(g["home"]), str(g["away"])))) or {}
        wins = os_.get("wins")
        if wins and os_.get("teams") and str(os_["teams"][0]) != str(g["home"]):
            wins = [wins[1], wins[0]]                       # as [home, away]
        x["sig"] = {"preseason": g.get("gtype") in ("S", "E"),
                    "series": {"game": ser.get("game"), "best_of": ser.get("of") or 7, "name": ser.get("desc"),
                               "wins": wins if g.get("status") != "final" else None} if ser.get("desc") else None,
                    "stage": "final" if g.get("gtype") == "W" else "semi" if g.get("gtype") == "L" else
                             "playoff" if g.get("gtype") in ("F", "D") else None,
                    "title": [p_ws.get(str(g["home"])), p_ws.get(str(g["away"]))] if p_ws else None}
        games.append(x)
    out["games"].extend(pick_games(ctx, games, 3, 4))
    out["pool"].extend(games)
    race_moves(out, ctx, "baseball", "MLB", race_log(d / "mlb" / "race_log.json", idx.get("season")), "p_postseason", tm, "postseason chance")
    hot_team(out, "baseball", "MLB", (idx.get("digest") or {}).get("hot"), tm((((idx.get("digest") or {}).get("hot")) or {}).get("key")))
    pteams = ps.get("teams") or {}
    rows = sorted(pteams.items(), key=lambda kv: -(kv[1].get("p_ws") or 0))
    rows = [(k, v) for k, v in rows if (v.get("p_ws") or 0) > 0]
    if rows:
        out["futures"]["baseball"] = {"title": "World Series", "rows": [
            {"name": (teams.get(k) or {}).get("name") or v.get("name"), "abbr": (teams.get(k) or {}).get("abbr"),
             "p": r4(v.get("p_ws")), "colour": (teams.get(k) or {}).get("colour"),
             "href": base + "#/mlb/team/" + k} for k, v in rows]}
    series = []
    for s in ps.get("series") or []:
        if not s.get("done"):
            a, b = s["teams"]
            series.append({"round": s.get("round_name"), "a": tm(a), "b": tm(b), "wins": s.get("wins"),
                           "p": [r4(x) for x in (s.get("p") or [])], "best_of": s.get("best_of")})
    out["charts"]["mlb_series"] = series

    lead = idx.get("leaders") or {}
    war = []
    for pid, v in (lead.get("h_war") or [])[:8]:
        p = pidx.get(str(pid)) or []
        war.append({"name": p[0] if p else pid, "team": (teams.get(str(p[1])) or {}).get("abbr") if len(p) > 1 else None,
                    "value": v, "href": base + "#/player/" + str(pid)})
    out["leaders"]["baseball"] = {"title": "Hitter WAR", "unit": "WAR", "rows": war,
                                  "hot": {"title": "Best season (WAR)",
                                          "expl": "WAR: wins added over a bench-level player. 5 or more is all-star level."}}
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
        miss = max(1, round(10 * (1 - (v0['p_ws'] or 0))))
        out["stats"].append({"sport": "baseball", "kicker": "World Series chance",
                             "title": f"The {(teams.get(k0) or {}).get('short') or (teams.get(k0) or {}).get('name')} are the favourites",
                             "note": f"<b>{v0['p_ws'] * 100:.0f}%</b> still means someone else wins it about "
                                     f"{miss} time{'s' if miss != 1 else ''} in 10.",
                             "value": f"{v0['p_ws'] * 100:.0f}%", "unit": (teams.get(k0) or {}).get("short"),
                             "text": f"The {(teams.get(k0) or {}).get('name')} are the model's World Series "
                                     f"favourite after 20,000 simulations of the bracket.",
                             "href": base + "#/postseason"})
    in_play = sorted({s["round"] for s in series if s.get("round")})
    return {"phase": (idx.get("phase") or "").capitalize(), "status": (nxt["round"] if nxt else idx.get("phase")),
            "stage": ("Postseason: " + ", ".join(in_play)) if in_play else PHASE_WORD.get(str(idx.get("phase")), str(idx.get("phase") or "")).capitalize(),
            "kpis": kp, "updated_at": idx.get("updated_at")}


# ───────────────────────────────────────────────────────────── NFL
NFL_ROUND = {"WC": "Wild Card", "DIV": "Divisional round", "CON": "Conference championship", "SB": "Super Bowl"}


def build_nfl(ctx: Ctx, base: str, out: dict):
    d = DOCS / "gridiron" / "data"
    idx = load(d / "index.json")
    if not idx:
        raise RuntimeError("index.json missing")
    pidx = load(d / "players_index.json") or {}
    teams = idx.get("teams") or {}

    def tm(a):
        t = teams.get(a) or {}
        return team(nickname(t.get("name")) if t.get("name") else a, a, t.get("colour"),
                    href=base + "#/team/" + a, full=t.get("name"), alt=t.get("alt"))

    po = idx.get("playoff_odds") or {}
    seen, games = set(), []
    for g in (idx.get("live") or []) + (idx.get("games") or []) + (idx.get("recent") or []):
        if g["game_id"] in seen:
            continue
        seen.add(g["game_id"])
        m = g.get("model") or {}
        gt = g.get("gtype") or "REG"
        x = game("nfl", "NFL", g["game_id"], g["kickoff"], g["status"], tm(g["home"]), tm(g["away"]),
                 g.get("hs"), g.get("as"), p_home=r4(m.get("p_home")), **mkt(g),
                 model_spread=m.get("spread"),
                 period=g.get("qtr"), clock=g.get("clock"), wp_home=r4(g.get("wp_home")),
                 note=NFL_ROUND.get(gt) or f"Week {g.get('week')}", href=base + "#/game/" + g["game_id"])
        ho, ao = po.get(g["home"]) or {}, po.get(g["away"]) or {}
        x["sig"] = {"preseason": gt == "PRE",
                    "stage": {"SB": "final", "CON": "semi", "DIV": "quarter", "WC": "playoff"}.get(gt),
                    "title": [ho.get("p_sb"), ao.get("p_sb")] if po and gt == "REG" else None,
                    "playoff": [ho.get("p_playoffs"), ao.get("p_playoffs")] if po and gt == "REG" else None}
        games.append(x)
    out["games"].extend(pick_games(ctx, games, 4, 10))
    out["pool"].extend(games)
    race_moves(out, ctx, "nfl", "NFL", race_log(d / "race_log.json", idx.get("season")), "p_playoffs", tm, "playoff chance")
    hot_team(out, "nfl", "NFL", (idx.get("digest") or {}).get("hot"), tm((((idx.get("digest") or {}).get("hot")) or {}).get("key")))
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
                             "title": f"The {((teams.get(ab) or {}).get('name', ab)).split(' ')[-1]} have moved the most",
                             "note": "<b>Rating points</b>: how many points a game better or worse than an average team "
                                     "our model rates a side.",
                             "value": f"{dlt:+.1f}", "unit": "rating points",
                             "text": f"The {(teams.get(ab) or {}).get('name', ab)} have moved {dlt:+.1f} points "
                                     f"per game against an average team since week {h[0][0]}.",
                             "href": base + "#/team/" + ab})
    k0 = rows[0] if rows else None
    ph = str(idx.get("phase") or "regular")
    return {"phase": f"Week {idx.get('week')}", "status": f"{idx.get('season')} regular season · week {idx.get('week')}",
            "stage": (f"Week {idx.get('week')} of the regular season" if ph.lower().startswith("reg")
                      else PHASE_WORD.get(ph, ph).capitalize()),
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
        return team(nickname(t.get("name")) if t.get("name") else a, a, t.get("colour"),
                    href=base + "#/team/" + a, full=t.get("name"), alt=t.get("alt"))

    po = idx.get("playoff_odds") or {}
    seen, games = set(), []
    for g in (idx.get("live") or []) + (idx.get("today") or []) + (idx.get("recent") or []) + (idx.get("upcoming") or []):
        if g["game_id"] in seen:
            continue
        seen.add(g["game_id"])
        m = g.get("model") or {}
        x = game("hockey", "NHL", g["game_id"], g.get("start"), g.get("status"), tm(g["home"]), tm(g["away"]),
                 g.get("hs"), g.get("as"), p_home=r4(m.get("p_home")), **mkt(g),
                 total=m.get("total"), period=g.get("period"), clock=g.get("clock"),
                 wp_home=r4(g.get("wp_home")), xg=[(g.get("xg") or {}).get("home"), (g.get("xg") or {}).get("away")] if g.get("xg") else None,
                 note=("OT" if g.get("ot") else None), href=base + "#/game/" + g["game_id"])
        ser = g.get("series") if isinstance(g.get("series"), dict) else {}
        ho, ao = po.get(g["home"]) or {}, po.get(g["away"]) or {}
        gtype = g.get("type") or "REG"
        reg = gtype == "REG"
        x["sig"] = {"preseason": gtype in ("PR", "PRE"),
                    "stage": None if reg or gtype in ("PR", "PRE") else "playoff",
                    "series": {"game": ser.get("game"), "best_of": 7, "wins": ser.get("wins"),
                               "name": ser.get("round") or ser.get("name")} if ser.get("game") else None,
                    "title": [ho.get("p_cup"), ao.get("p_cup")] if po and reg else None,
                    "playoff": [ho.get("p_playoffs"), ao.get("p_playoffs")] if po and reg else None}
        games.append(x)
    out["games"].extend(pick_games(ctx, games, 5, 8))
    out["pool"].extend(games)
    race_moves(out, ctx, "hockey", "NHL", race_log(d / "race_log.json", idx.get("season")), "p_playoffs", tm, "playoff chance")
    hot_team(out, "hockey", "NHL", (idx.get("digest") or {}).get("hot"), tm((((idx.get("digest") or {}).get("hot")) or {}).get("key")))
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
    gp_max = max([r.get("gp") or 0 for r in srows] or [0])
    out["leaders"]["hockey"]["hot"] = {"title": "Most points",
                                       "expl": "Points = goals + assists." + (f" {gp_max} games in, so it is early."
                                                                               if 0 < gp_max < 25 else "")}
    gs = []
    for pid, v in (lead.get("g_gsax") or [])[:1]:
        p = pidx.get(pid) or []
        gs.append((p[0] if p else pid, p[1] if len(p) > 1 else None, v, pid))
    if gs:
        nm, tmab, v, pid = gs[0]
        out["stats"].append({"sport": "hockey", "kicker": "Best in net", "value": f"{v:+.1f}",
                             "title": f"{surname(nm)} has been a wall" if v >= 5 else f"{surname(nm)} leads in net",
                             "note": "<b>Goals saved above expected</b> compares each shot faced with how often that kind "
                                     "of shot goes in. Positive means better than an average goalie.",
                             "unit": "goals saved above expected",
                             "text": f"{nm} ({tmab}) has saved {v:.1f} more goals than an average goalie would on "
                                     f"the same shots this season.", "href": base + "#/player/" + pid})
    for k, t in teams.items():
        out["search"].append(["hockey", t.get("name"), "NHL team · " + (t.get("division") or ""), base + "#/team/" + k])
    k0 = rows[0] if rows else None
    top = srows[0] if srows else None
    ph = str(idx.get("phase") or "regular")
    return {"phase": (idx.get("phase") or "").capitalize(),
            "stage": (("Regular season" + (f", {gp_max} games in" if gp_max else "")) if ph.lower().startswith("reg")
                      else PHASE_WORD.get(ph, ph).capitalize()),
            "status": f"{sum(1 for g in games if g['status'] == 'live' and in_window(ctx, g))} live · "
                      f"{len(idx.get('upcoming') or [])} upcoming",
            "kpis": [{"label": "Cup fav", "value": (teams.get(k0[0]) or {}).get("name", "—").split(" ")[-1] if k0 else "—",
                      "sub": f"{k0[1]['p_cup'] * 100:.0f}%" if k0 else None},
                     {"label": "1st", "value": top["team"] if top else "—",
                      "sub": f"{top['pts']} pts" if top else None},
                     {"label": "Points", "value": surname(pts[0]["name"]) if pts else "—",
                      "sub": f"{pts[0]['value']} pts" if pts else None}],
            "updated_at": idx.get("updated_at")}


# ───────────────────────────────────────────────────────────── college
COLLEGE_TITLE = {"cfb": "College football national title", "mbb": "Men's college basketball title",
                 "wbb": "Women's college basketball title"}


def build_college(ctx: Ctx, base: str, out: dict):
    """The Quant Campus: docs/campus/data/index.json (oddsmarkets/college/site.py) and its search.json.

    Futures: one entry per level, like hardwood's two leagues: `college` (CFB), `college_mbb`, `college_wbb`
    (home.js shows them as the CFB, MBB and WBB tabs)."""
    d = DOCS / "campus" / "data"
    idx = load(d / "index.json")
    if not idx or not idx.get("levels"):
        raise RuntimeError("index.json missing")
    status, kpis, stages = [], [], []
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
                        href=base + "#/" + L + "/team/" + str(tid), full=t.get("name"), alt=t.get("alt") or t.get("alt_colour"))

        tp = {r.get("team"): r.get("p") for r in lg.get("title_odds") or [] if r.get("team")}
        seen, games = set(), []
        for g in (lg.get("today") or []) + (lg.get("next_games") or []) + (lg.get("last_games") or []):
            if g.get("id") in seen or (g.get("tba") and norm_status(g.get("status")) == "pre"):
                continue                       # a game whose start time is not set (TBA) has no slot on the home page
            seen.add(g.get("id"))
            m = g.get("model") or {}
            note = g.get("round") if g.get("stype") in ("cfp", "ncaa", "bowl") else None
            href = base + "#/" + L + "/game/" + str(g["id"]) + ("" if g.get("season") in (None, S) else f"?season={g['season']}")
            x = game("college", LU, g["id"], g.get("date"), g.get("status"), tm(g["home"], g.get("hr")),
                     tm(g["away"], g.get("ar")), g.get("hs"), g.get("as"), p_home=r4(m.get("p_home")), **mkt(g),
                     total=m.get("total"),
                     note=note, href=href)
            rnd = str(g.get("round") or "")
            stage = None
            if re.search(r"National Championship|Championship Game|^Final\b", rnd):
                stage = "final"
            elif re.search(r"Semifinal|Final Four", rnd):
                stage = "semi"
            elif g.get("stype") in ("cfp", "ncaa"):
                stage = "playoff"
            elif g.get("stype") == "bowl":
                stage = "knockout"
            x["sig"] = {"comp": LU, "preseason": g.get("stype") == "pre", "stage": stage,
                        "ranks": [g.get("hr"), g.get("ar")],
                        "title": [tp.get(str(g["home"])), tp.get(str(g["away"]))] if tp else None}
            games.append(x)
        out["games"].extend(pick_games(ctx, games, 4, 6))
        out["pool"].extend(games)
        race_moves(out, ctx, "college", LU, race_log(d / L / "race_log.json", S), "p_cfp" if L == "cfb" else "p_ncaa", tm,
                   "College Football Playoff chance" if L == "cfb" else "NCAA tournament chance")
        rows = [r for r in (lg.get("title_odds") or []) if r.get("p")][:8]
        if rows:
            out["futures"]["college" if L == "cfb" else "college_" + L] = {
                "title": COLLEGE_TITLE[L], "rows": [
                    {"name": (teams.get(r["team"]) or {}).get("name") or r["team"], "abbr": (teams.get(r["team"]) or {}).get("abbr"),
                     "p": r4(r["p"]), "colour": (teams.get(r["team"]) or {}).get("colour"),
                     "href": base + "#/" + L + "/team/" + r["team"]} for r in rows]}
            t0 = teams.get(rows[0]["team"]) or {}
            kpis.append({"label": f"{LU} fav", "value": t0.get("short") or t0.get("name") or rows[0]["team"],
                         "sub": f"{(rows[0]['p'] or 0) * 100:.0f}% title"})
        status.append(f"{LU} {phase_lab.get(lg.get('phase'), lg.get('phase') or '')}".strip())
        if lg.get("phase") not in (None, "offseason"):
            stages.append(f"{LU} {phase_lab.get(lg.get('phase'), lg.get('phase') or '')}".strip())
    srch = load(d / "search.json") or []
    for r in srch if isinstance(srch, list) else []:
        if r.get("t") and r.get("href"):
            out["search"].append(["college", r["t"], r.get("s") or "", base + r["href"]])
    return {"phase": " · ".join(status), "status": " · ".join(status), "kpis": kpis[:3],
            "stage": " · ".join(stages) or " · ".join(status), "updated_at": idx.get("updated_at")}


def pct_text(p):
    """0.9999 -> '>99.9%', 0.0004 -> '<0.1%', else one decimal under 10% and whole numbers above."""
    if p is None:
        return "—"
    p = float(p)
    if p > 0.999:
        return ">99.9%"
    if 0 < p < 0.001:
        return "<0.1%"
    return f"{p * 100:.1f}%" if p < 0.1 else f"{p * 100:.0f}%"


# ───────────────────────────────────────────────────────────── Matchday copy: why a game is worth watching
PLAYER_SPORTS = {"tennis", "f1"}
THE_SPORTS = {"nfl", "hockey", "baseball", "basketball"}   # team names here are nicknames: "the Ravens"; football and
                                                          # college names stand alone ("Arsenal are", "Ohio State are")


def _a(n):
    """The article before a percentage: 'an 18% chance', 'a 31% chance'."""
    return "an" if str(n).startswith("8") or n in (11, 18) else "a"


def _fav(g):
    """(favourite team dict, its chance, the other team, the other's chance, draw) from our numbers (live: wp_home)."""
    live = g["status"] == "live" and g.get("wp_home") is not None
    ph = g.get("wp_home") if live else g.get("p_home")
    if ph is None:
        return None
    pd = 0.0 if live else (g.get("p_draw") or 0.0)
    pa = 1 - ph if live else (g.get("p_away") if g.get("p_away") is not None else 1 - ph - pd)
    if pa > ph:
        return g["away"], pa, g["home"], ph, pd
    return g["home"], ph, g["away"], pa, pd


def _name(g, t):
    n = t.get("name") or t.get("abbr") or ""
    return "the " + n if g["sport"] in THE_SPORTS and not g.get("players") else n


def _favourite_phrase(g, t, kind):
    """'the Knicks are clear favourites' / 'J. Sinner is a clear favourite'."""
    if g["sport"] in PLAYER_SPORTS or g.get("players"):
        return f"{_name(g, t)} is a {kind} favourite"
    return f"{_name(g, t)} are {kind} favourites"


def why_line(g):
    """One friendly line on why a game is worth watching, from our numbers only (STYLE_GUIDE: never the market).
    None when there is nothing better to say than the card already shows (the front end then writes its own)."""
    st = g.get("status")
    if st == "final" or g.get("event"):
        return None
    note = str(g.get("note") or "")
    game_no = re.search(r"\bG(\d)\b|Game (\d)", note)
    game_no = (game_no.group(1) or game_no.group(2)) if game_no else None
    f = _fav(g)
    if st == "live":
        wp, ph = g.get("wp_home"), g.get("p_home")
        if wp is not None and ph is not None and abs(wp - ph) >= 0.08:
            pre_home = ph >= 0.5
            t = g["home"] if pre_home else g["away"]
            return f"Before the start we had {_name(g, t)} at {round((ph if pre_home else 1 - ph) * 100)}%. The score has moved it."
        return None
    if game_no == "7":
        if g["sport"] == "baseball" and "CS" in note:
            return "Game 7. The winner goes to the World Series."
        return "Game 7. The winner goes through."
    if f is None:
        return None
    t, fp, o, op, pd = f
    if game_no and "Finals" in note:
        lead = f"Game {game_no} of the {note.split(' Finals')[0].split(' · ')[0]} Finals. "
    else:
        lead = ""
    if pd >= 0.3:
        return lead + f"A draw is live: {round(pd * 100)}% in our numbers."
    if fp - op < 0.08:
        k = sum(ord(c) for c in str(g.get("id") or "")) % 3
        return lead + ["A coin flip: we can barely split them.",
                       f"Too close to call: {round(fp * 100)}% to {round(op * 100)}%.",
                       f"Nothing between them: {round(fp * 100)}% to {round(op * 100)}%."][k]
    nm = _name(g, t)
    nm = nm[0].upper() + nm[1:]
    if pd >= 0.2 and fp < 0.55:
        return lead + f"{nm} shade it at {round(fp * 100)}%, with the draw at {round(pd * 100)}%."
    if fp >= 0.66:
        u = max(0.01, 1 - fp - pd)
        ph = _favourite_phrase(g, t, "clear")
        lose = "loses" if g["sport"] in PLAYER_SPORTS or g.get("players") else "lose"
        if pd >= 0.05:
            return lead + ph[0].upper() + ph[1:] + f", but they still {lose} about 1 time in {round(1 / u)}."
        uu = round(u * 100)
        return lead + ph[0].upper() + ph[1:] + f", but {_a(uu)} {uu}% chance comes off about 1 time in {round(1 / u)}."
    ph = _favourite_phrase(g, t, "slight")
    return lead + ph[0].upper() + ph[1:] + f" at {round(fp * 100)}%."


def add_why(games):
    """Write games[].why; the closest two-way call among the upcoming games is named as such."""
    for g in games:
        w = why_line(g)
        if w:
            g["why"] = w
    pre = [g for g in games if g["status"] == "pre" and not g.get("event") and g.get("p_home") is not None
           and g.get("p_draw") is None]
    if pre:
        c = min(pre, key=lambda g: abs(g["p_home"] - 0.5))
        if abs(c["p_home"] - 0.5) < 0.04 and not re.search(r"\bG7\b|Game 7", str(c.get("note") or "")):
            c["why"] = "A coin flip: our closest call on the slate."


# ───────────────────────────────────────────────────────────── "How sure are we?" (calibration)
CALIBRATION = [
    # key, folder, path under data/, league, subject
    ("hockey", "rink", "calibration.json", "NHL", "the home team"),
    ("basketball", "hardwood", "nba/calibration.json", "NBA", "the home team"),
    ("nfl", "gridiron", "calibration.json", "NFL", "the home team"),
    ("baseball", "bullpen", "mlb/calibration.json", "MLB", "the home team"),
]


def _cal_block(b):
    if not isinstance(b, dict) or not isinstance(b.get("reliability"), list):
        return None
    return b


def _season_label(x):
    x = str(x)
    if len(x) == 8:                                  # 20092010 -> 2009-10
        return f"{x[:4]}-{x[6:]}"
    return x


def calibration_summary(docs: Path = DOCS):
    """{ sport: { league, span, n, brier, logloss, subject, unit, bins } } from each site's calibration.json. The
    game model's pre-game home-win forecasts, every season the file was scored on (Bullpen: seasons pooled)."""
    out = {}
    for key, folder, rel, league, subject in CALIBRATION:
        j = load(docs / folder / "data" / rel)
        if not j:
            continue
        blk, seasons = None, []
        gm = j.get("game_model") if isinstance(j.get("game_model"), dict) else None
        if gm and _cal_block((gm.get("metrics") or {}).get("model")):
            blk, seasons = gm["metrics"]["model"], gm.get("seasons") or []
        elif _cal_block((j.get("metrics") or {}).get("model")):
            blk, seasons = j["metrics"]["model"], j.get("seasons") or []
        elif isinstance((j.get("games") or {}).get("seasons"), dict):
            ss = j["games"]["seasons"]
            by, n, br = {}, 0, 0.0
            for yr, v in ss.items():
                m = _cal_block((v or {}).get("model"))
                if not m:
                    continue
                seasons.append(yr)
                n += m.get("n") or 0
                br += (m.get("brier") or 0) * (m.get("n") or 0)
                for b in m["reliability"]:
                    t = by.setdefault(b["lo"], {"lo": b["lo"], "hi": b["hi"], "n": 0, "sp": 0.0, "sf": 0.0})
                    t["n"] += b["n"]
                    t["sp"] += b["mean_p"] * b["n"]
                    t["sf"] += b["freq"] * b["n"]
            if n:
                blk = {"n": n, "brier": br / n, "reliability": [
                    {"lo": t["lo"], "hi": t["hi"], "n": t["n"], "mean_p": t["sp"] / t["n"], "freq": t["sf"] / t["n"]}
                    for t in sorted(by.values(), key=lambda t: t["lo"]) if t["n"]]}
        if not blk:
            continue
        seasons = sorted(seasons, key=str)
        out[key] = {"league": league, "subject": subject, "unit": "games",
                    "span": f"{_season_label(seasons[0])} to {_season_label(seasons[-1])}" if seasons else None,
                    "n": blk.get("n"), "brier": r4(blk.get("brier")), "logloss": r4(blk.get("logloss")),
                    "bins": [{"lo": b["lo"], "hi": b["hi"], "n": b["n"], "mean_p": r4(b["mean_p"]), "freq": r4(b["freq"])}
                             for b in blk["reliability"] if b.get("n")]}
    return out


# ───────────────────────────────────────────────────────────── the top of the page: the game of the day and the digest
# Sports whose finished games keep the chance we published before the start (frozen at the last pre-game build, or
# rebuilt as of the day before with ratings that exclude the game): MLB, NFL, NHL frozen; NBA/WNBA, tennis and college
# computed as of the day before. Football drops its forecast once a match is finished, so it has no pre-game chance
# to count and is left out of "Our record this week" (the page says so).
RECORD_SPORTS = ("nfl", "hockey", "baseball", "basketball", "tennis", "college")


def _matchup(g):
    if g.get("event"):
        return g["home"].get("name") or "Grand Prix"
    sep = " v "
    return (g["home"]["name"] + sep + g["away"]["name"]) if g["sport"] == "football" else (g["away"]["name"] + sep + g["home"]["name"])


RECORD_MIN_N = 20     # under this many finished games the week says little: widen to 14 days, and say so


def record_with_floor(games, now):
    """Our favourites' record over the last 7 days, or the last 14 when the week has under RECORD_MIN_N finished games
    (`days` says which). The front end calls anything still under RECORD_MIN_N a small sample."""
    rec = DG.record(games, now, days=7)
    if rec is None or rec["n"] < RECORD_MIN_N:
        wide = DG.record(games, now, days=14)
        if wide is not None and (rec is None or wide["n"] > rec["n"]):
            return dict(wide, days=14)
    return dict(rec, days=7) if rec else None


def top_of_page(now, games, pool, series, sports):
    """featured, digest and sports[].topline (module docstring), and games[].weight. Adds the featured games to
    `games` when the per-sport pick left them out."""
    ranked = FT.rank_featured(pool, now)
    by_key = {FT.game_key(g): g for g in pool}
    shown = {FT.game_key(g) for g in games}
    for row in ranked["today"] + ([ranked["week"]] if ranked["week"] else []):
        g = by_key.get(row["key"])
        if g is not None and row["key"] not in shown:
            games.append(g)
            shown.add(row["key"])
    for g in games:
        if g["status"] in ("pre", "live"):
            g["weight"] = FT.significance(g, now)["score"]

    def slim(row):
        return None if not row else {"key": row["key"], "score": row["score"], "reasons": row["reasons"]}
    featured = {"today": [slim(r) for r in ranked["today"]], "week": slim(ranked["week"])}

    honest = [g for g in pool if g["sport"] in RECORD_SPORTS]
    rec = record_with_floor(honest, now)
    up = DG.upset(honest, now, full=True)
    upset = None
    if up:
        g = up["game"]
        w, l_ = up["winner"], up["loser"]
        upset = {"sport": g["sport"], "league": g.get("league"), "start": g["start"], "p": up["p"],
                 "winner": w.get("name"), "loser": l_.get("name"), "winner_abbr": w.get("abbr"),
                 "score": [g.get("hs"), g.get("as")] if up["side"] == "home" else [g.get("as"), g.get("hs")],
                 "players": bool(g.get("players")), "href": g.get("href")}
    swing = DG.swing(series, now)
    digest = {"record": rec, "upset": upset, "swing": swing,
              "record_sports": sorted({b["sport"] for b in (rec or {}).get("by", [])}),
              "left_out": ["football"]}

    # one line per sport: where the season is, and its most significant game or event in the next 7 days
    for sp in sports:
        if not sp.get("ok"):
            continue
        cands = [g for g in pool if g["sport"] == sp["key"] and g["status"] in ("pre", "live")]
        best = FT.rank_featured(cands, now, min_score=-1e9)
        row = (best["today"] or [None])[0] or best["week"]
        if row is None:                    # nothing in the week (an F1 gap week): the next scheduled game or event
            later = sorted((g for g in cands if g["status"] == "pre" and g.get("start") and parse_ts(g["start"]) >= now),
                           key=lambda g: g["start"])
            row = {"key": FT.game_key(later[0])} if later else None
        nxt = None
        if row:
            g = by_key[row["key"]]
            nxt = {"title": _matchup(g), "start": g["start"], "league": g.get("league"), "href": g.get("href"),
                   "live": g["status"] == "live", "tba": g.get("tba")}
        sp["topline"] = {"stage": sp.pop("stage", None) or sp.get("status"), "next": nxt}
        sp.pop("stage", None)
    return {"featured": featured, "digest": digest}


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


def season_files(docs: Path = DOCS):
    """The per-season files this build reads beyond each site's fixed summaries, as (folder, repo, path) rows.

    In CI the sport trees are not on disk: the home workflow downloads each site's index.json (and the other
    fixed files) from the live sites, then asks for this list so it can fetch the files whose paths depend on
    the current season. Without them F1 standings and title odds, basketball futures, NFL rating movers, NHL
    standings and the football title races were silently empty on the live home page (accuracy audit, 22 Oct 2026).
    """
    rows = []
    for slug in TITLE_LEAGUES:
        rows += [("site", "the-quant-footballer", f"{slug}/probs.json"),
                 ("site", "the-quant-footballer", f"{slug}/history.json")]   # title chance over time: the week's swing
    idx = load(docs / "paddock" / "data" / "index.json") or {}
    if idx.get("current_season"):
        rows.append(("paddock", "the-quant-paddock", f"{idx['current_season']}/season.json"))
    idx = load(docs / "hardwood" / "data" / "index.json") or {}
    for L, lg in (idx.get("leagues") or {}).items():
        if lg.get("current_season"):
            rows.append(("hardwood", "the-quant-hardwood", f"{L}/{lg['current_season']}/season.json"))
    for folder in ("gridiron", "rink"):
        idx = load(docs / folder / "data" / "index.json") or {}
        if idx.get("season"):
            rows.append((folder, f"the-quant-{folder}", f"{idx['season']}/season.json"))
    # the season's biggest surprises (fan stories) read each site's race log (fixed paths, for sites present)
    for folder, rels in (("rink", ["race_log.json"]), ("gridiron", ["race_log.json"]), ("bullpen", ["mlb/race_log.json"]),
                         ("hardwood", ["nba/race_log.json", "wnba/race_log.json"]),
                         ("campus", ["cfb/race_log.json", "mbb/race_log.json", "wbb/race_log.json"])):
        if (docs / folder / "data" / "index.json").exists():
            rows += [(folder, f"the-quant-{folder}", rel) for rel in rels]
    # "How sure are we?" reads each site's calibration.json (fixed paths, listed here so CI fetches them too)
    for key, folder, rel, league, subject in CALIBRATION:
        if (docs / folder / "data" / "index.json").exists():
            rows.append((folder, f"the-quant-{folder}", rel))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season-files", action="store_true",
                    help="print the season-dependent files to fetch ('<folder> <repo> <path>' per line) and exit")
    ap.add_argument("--links", choices=["public", "local"], default="public")
    ap.add_argument("--no-kit", action="store_true", help="do not copy docs/_design into docs/home/assets/qk")
    ap.add_argument("--now", help="build as of this UTC time (ISO), to preview an older local snapshot")
    ap.add_argument("--with-pending", action="store_true",
                    help="include sites not launched yet (PENDING, e.g. The Quant Campus) for local preview")
    a = ap.parse_args(argv)
    if a.season_files:
        for row in season_files():
            print(" ".join(row))
        return
    now = parse_ts(a.now) if a.now else datetime.now(timezone.utc).replace(microsecond=0)
    ctx = Ctx(a.links, now)
    out = {"games": [], "futures": {}, "leaders": {}, "charts": {}, "stats": [], "search": [], "pool": [], "series": [],
           "races": [], "hot_teams": []}
    sports = []
    for key, folder, repo, label, site in SPORTS + [x for x in PENDING if x[0] in LAUNCHED or a.with_pending]:
        base = ctx.base(folder, repo)
        entry = {"key": key, "label": label, "site": site, "url": base, "data": PUBLIC.format(repo) + "data/",
                 "ok": False}
        part = {"games": [], "futures": {}, "leaders": {}, "charts": {}, "stats": [], "search": [], "pool": [], "series": [],
                "races": [], "hot_teams": []}
        try:
            entry.update(BUILDERS[key](ctx, base, part))
            if key == "football":
                football_search(base, part)
        except Exception as exc:  # one sport failing never takes the others down
            log(f"{key}: skipped ({exc!r})")
        else:
            entry["ok"] = True
            upd = parse_ts(entry.get("updated_at"))
            if upd:  # how old this sport's input is, so a stale tile can say so instead of looking current
                entry["age_hours"] = round((now - upd).total_seconds() / 3600, 1)
                entry["stale"] = entry["age_hours"] > STALE_HOURS
            for k, v in part.items():
                if isinstance(v, list):
                    out[k].extend(v)
                else:
                    out[k].update(v)
        sports.append(entry)
    pool, series = out.pop("pool"), out.pop("series")
    top = top_of_page(now, out["games"], pool, series, sports)
    top["stories"] = fan_stories(out.pop("races"), out.pop("hot_teams"))
    out["games"].sort(key=lambda g: ({"live": 0, "pre": 1, "final": 2}[g["status"]], g["start"] or ""))
    add_why(out["games"])
    for g in pool:
        g.pop("sig", None)                 # hints for the significance score only; never written
    out["calibration"] = calibration_summary()
    search = out.pop("search")
    home = {"version": 1, "updated_at": iso(now), "links": a.links, "sports": sports, **out, **top}
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    with open(OUT / "data" / "home.json", "w", encoding="utf-8") as fh:
        json.dump(home, fh, ensure_ascii=False, separators=(",", ":"))
    with open(OUT / "data" / "search.json", "w", encoding="utf-8") as fh:
        json.dump({"fields": ["sport", "name", "sub", "href"], "rows": [s for s in search if s[1]]},
                  fh, ensure_ascii=False, separators=(",", ":"))
    if not a.no_kit:
        copy_kit()
    sz = (OUT / "data" / "home.json").stat().st_size
    log(f"home.json {sz / 1024:.0f} KB · {len(out['games'])} games · "
        f"{sum(1 for s in sports if s['ok'])}/{len(sports)} sports · {len(search)} search rows")


if __name__ == "__main__":
    main()
