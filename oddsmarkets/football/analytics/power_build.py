"""The Quant Footballer's power rankings: data/power/<league>.json for every domestic league with a table and the site
index data/power.json (the shape is oddsmarkets/common/power.py; the kit's power.js draws them on #/power?l=<league>
and on Home). Cups, super cups and national-team tournaments have no file. The default league is the Premier League.

Read from the payloads the build has just written (no new fetching, no new model):

    competitions.json           the leagues (kind league, conference, playoff, liga, torneo), their current season,
                                games played, the label of the title chance
    clubs_index.json            club colours, by team id
    <league>/teams.json         name -> team id
    <league>/strength.json      elo_history (our Elo, replayed over this season's league games from where each club
                                finished last season: one dated entry per game), form, xG for and against, our
                                points-a-game rating (strength_ppg, the Teams pages' rating)
    <league>/table.json         the table: position, points, W-D-L (MLS: its conference tables; Argentina: zones.json,
                                the Clausura's zones, since table.json is the Tabla Anual there)
    <league>/probs.json         our title chance (MLS and Liga MX: the play-off title, p_cup)
    lab/season/<league>.json    each player's season in the league (the Scouting Room's rows): formation role,
                                minutes, GAR/90, per-90 numbers

    build(data_root, now=None) -> {"n", "bytes", "max", "leagues"}     (python -m oddsmarkets.football.analytics.power_build)

The ranking is the Elo replay because it is the one rating with a game-by-game history: strength_ppg (refitted every
build) has none, so a past week's ranking on it cannot be rebuilt without look-ahead. The rating shown is a club's Elo
minus the league's average (the replay is zero-sum, so the average never moves); strength_ppg is a stat beside it.

Snapshots, no look-ahead: an elo_history entry is the rating AFTER its game (checked on the 13 Nov 2026 payloads: in
the Premier League, La Liga and the Bundesliga every one of 405 entries dated on a single win or loss moved with that
result; against the game before it the sign agreed about half the time, as chance would. Liverpool lost 0-3 at home
to Manchester City on 11 Oct and their 11 Oct entry fell from 1731.7 to 1718.1). A snapshot dated D is every club's
last entry dated on or before D: the games up to that day only. Snapshots are seven days apart, counted back from the
latest league game ("Now"), so each step holds about one round for every club whatever day a round starts: a Friday
game does not reset every other move to zero, and an international break keeps the last round as the move. A week
with no league game is skipped (its ranking is the week before's). Play-off games are not in the replay: in a
play-off (MLS, Argentina) the ranking stands where the league season ended.
"""
from __future__ import annotations

import gzip
import json
import logging
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import power as PW

log = logging.getLogger(__name__)

SITE, SPORT = "site", "football"
DEFAULT = "premier-league"
LEAGUE_KINDS = ("league", "conference", "playoff", "liga", "torneo")
STEP_DAYS = 7
# shorter labels for the league chips and Home's picker (the rest use the competition's own name)
LABEL = {"brasileirao": "Brasileirão", "mls": "MLS", "belgian-pro-league": "Belgian Pro League",
         "primera-a-colombia": "Colombia Primera A", "primera-division-uruguay": "Uruguay Primera División",
         "liga-de-primera": "Chile Liga de Primera", "liga-1-peru": "Peru Liga 1", "liga-argentina": "Liga Argentina",
         "primeira-liga": "Liga Portugal"}

# The front end's club codes (docs/site/assets/app/core.js clubCode): the codes the clubs and broadcasts use where a
# made-up one would be wrong, else one word -> its first three letters, two -> the first letter and the second word's
# first two, three or more -> the initials of the words that count
CLUB_CODES = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU", "AFC Bournemouth": "BOU", "Brentford": "BRE",
    "Brighton & Hove Albion": "BHA", "Brighton": "BHA", "Burnley": "BUR", "Chelsea": "CHE", "Crystal Palace": "CRY",
    "Everton": "EVE", "Fulham": "FUL", "Leeds United": "LEE", "Leeds": "LEE", "Liverpool": "LIV", "Manchester City": "MCI",
    "Manchester United": "MUN", "Newcastle United": "NEW", "Newcastle": "NEW", "Nottingham Forest": "NFO", "Sunderland": "SUN",
    "Tottenham Hotspur": "TOT", "Tottenham": "TOT", "West Ham United": "WHU", "West Ham": "WHU", "Wolverhampton": "WOL",
    "Wolverhampton Wanderers": "WOL", "Wolves": "WOL", "Ipswich Town": "IPS", "Ipswich": "IPS", "Leicester City": "LEI",
    "Southampton": "SOU", "Real Madrid": "RMA", "Barcelona": "BAR", "FC Barcelona": "BAR", "Atlético Madrid": "ATM",
    "Atletico Madrid": "ATM", "Athletic Club": "ATH", "Real Betis": "BET", "Real Sociedad": "RSO", "Rayo Vallecano": "RAY",
    "Celta Vigo": "CEL", "Real Oviedo": "OVI", "Real Valladolid": "VLL", "Villarreal": "VIL", "Valencia": "VAL",
    "Bayern München": "FCB", "FC Bayern München": "FCB", "Bayern Munich": "FCB", "Borussia Dortmund": "BVB",
    "Bayer 04 Leverkusen": "B04", "Bayer Leverkusen": "B04", "Borussia Mönchengladbach": "BMG", "RB Leipzig": "RBL",
    "Eintracht Frankfurt": "SGE", "VfB Stuttgart": "VFB", "Paris Saint-Germain": "PSG", "Olympique de Marseille": "OM",
    "Marseille": "OM", "Olympique Lyonnais": "OL", "Lyon": "OL", "AS Monaco": "ASM", "Monaco": "ASM", "Inter": "INT",
    "Inter Milan": "INT", "Milan": "MIL", "AC Milan": "MIL", "Juventus": "JUV", "Napoli": "NAP", "Roma": "ROM", "AS Roma": "ROM",
    "Lazio": "LAZ", "Atalanta": "ATA", "Fiorentina": "FIO", "Ajax": "AJA", "PSV Eindhoven": "PSV", "PSV": "PSV",
    "Feyenoord": "FEY", "Sporting CP": "SCP", "Benfica": "SLB", "SL Benfica": "SLB", "FC Porto": "POR", "Porto": "POR",
    "Celtic": "CLT", "Rangers": "RAN", "Al-Hilal": "HIL", "Al Hilal": "HIL", "Al-Nassr": "NAS", "Al Nassr": "NAS",
    "Al-Ittihad": "ITT", "Al Ittihad": "ITT", "Al-Ahli": "AHL", "Al Ahli": "AHL", "Inter Miami CF": "MIA", "Inter Miami": "MIA",
    "LA Galaxy": "LAG", "Los Angeles FC": "LAFC", "Boca Juniors": "BOC", "River Plate": "RIV", "Flamengo": "FLA",
    "Palmeiras": "PAL", "América": "AME", "Club América": "AME", "Cruz Azul": "CAZ", "Club Brugge KV": "BRU", "Club Brugge": "BRU",
}
CODE_SKIP = {"fc", "cf", "afc", "sc", "ac", "ca", "cd", "club", "de", "del", "da", "do", "of", "the", "and"}

# position groups: (key, label, short, formation roles, minimum minutes, stats [(key, label, fmt, tip)]); the keys are
# the Scouting Room's spec groups. GAR/90 leads every group (the Scouting Room's value column, the value model).
GROUPS = [
    ("gk", "Goalkeepers", "GK", ("GK",), 900,
     [("save_pct", "Save %", "1", "Share of shots on target saved"), ("goals_prevented_90", "Prevented/90", "+2", "Goals prevented per 90: post-shot xG faced minus goals conceded"),
      ("saves_90", "Saves/90", "2", None), ("conceded_90", "Conceded/90", "2", None), ("minutes", "Mins", "0", "League minutes this season")]),
    ("cb", "Centre-backs", "CB", ("CB",), 450,
     [("padj_tkl_int_90", "Tkl+Int/90", "2", "Tackles plus interceptions per 90, adjusted for the team's possession"),
      ("aerials_won_90", "Aerials won/90", "2", None), ("aerial_pct", "Aerial %", "1", "Share of aerial duels won"),
      ("pass_pct", "Pass %", "1", "Share of passes completed"), ("minutes", "Mins", "0", "League minutes this season")]),
    ("fb", "Full-backs", "FB", ("FB",), 450,
     [("assists", "Assists", "0", None), ("xa_90", "xA/90", "2", "Expected assists per 90"), ("crosses_90", "Crosses/90", "2", "Accurate crosses per 90"),
      ("padj_tkl_int_90", "Tkl+Int/90", "2", "Tackles plus interceptions per 90, adjusted for the team's possession"), ("minutes", "Mins", "0", "League minutes this season")]),
    ("dm_cm", "Midfielders", "DM/CM", ("DM", "CM"), 450,
     [("goals", "Goals", "0", None), ("assists", "Assists", "0", None), ("key_passes_90", "Key passes/90", "2", "Passes that set up a shot, per 90"),
      ("padj_tkl_int_90", "Tkl+Int/90", "2", "Tackles plus interceptions per 90, adjusted for the team's possession"), ("minutes", "Mins", "0", "League minutes this season")]),
    ("am_w", "Wingers and No. 10s", "AM/W", ("AM", "W"), 450,
     [("goals", "Goals", "0", None), ("assists", "Assists", "0", None), ("npxg_xa_90", "npxG+xA/90", "2", "Non-penalty expected goals plus expected assists per 90"),
      ("dribbles_90", "Dribbles/90", "2", "Successful take-ons per 90"), ("minutes", "Mins", "0", "League minutes this season")]),
    ("st", "Strikers", "ST", ("ST",), 450,
     [("goals", "Goals", "0", None), ("xg", "xG", "1", "Expected goals from the player's shots, penalties included"), ("assists", "Assists", "0", None),
      ("shots_90", "Shots/90", "2", None), ("minutes", "Mins", "0", "League minutes this season")]),
]
TOTALS = {"goals": "goals_90", "assists": "assists_90", "xg": "xg_90"}     # season totals from the per-90 rates
METRIC = {"key": "gar90", "label": "GAR/90", "unit": "goals per 90", "fmt": "+2", "dir": "higher",
          "tip": "Value added: goals of expected goal difference a player adds per 90 minutes over a replacement-level player in the same role, from our player value model."}
# the names the climb's end labels, the movers and Home's strip show (the list keeps the full name)
SHORT = {"Manchester City": "Man City", "Manchester United": "Man Utd", "Nottingham Forest": "Nott'm Forest",
         "Crystal Palace": "Palace", "Wolverhampton": "Wolves", "Wolverhampton Wanderers": "Wolves", "Atlético Madrid": "Atlético",
         "Athletic Club": "Athletic", "Rayo Vallecano": "Rayo", "Real Sociedad": "La Real", "Bayern München": "Bayern",
         "Borussia Dortmund": "Dortmund", "Borussia Mönchengladbach": "Gladbach", "Bayer 04 Leverkusen": "Leverkusen",
         "Eintracht Frankfurt": "Frankfurt", "Paris Saint-Germain": "PSG", "Olympique de Marseille": "Marseille",
         "Club Atlético Peñarol": "Peñarol", "Vancouver Whitecaps": "Vancouver", "Philadelphia Union": "Philadelphia",
         "Universidad Católica": "U. Católica", "Universidad de Chile": "U. de Chile", "Universitario de Deportes": "Universitario",
         "Atlético Nacional": "Nacional", "América de Cali": "América", "Independiente Medellín": "Medellín",
         "Argentinos Juniors": "Argentinos", "Rosario Central": "Rosario C.", "Club Sporting Cristal": "Sporting Cristal",
         "Montevideo City Torque": "City Torque"}
SHORT_PREFIX = ("Club Atlético ", "Club Deportivo ", "Club ", "Deportivo ", "CA ", "CD ", "FC ", "SC ", "AC ", "AFC ")


def _read(p: Path):
    """A payload as JSON: the plain file, else its .json.gz (the deploy gzips the bulky kinds, lab/ among them)."""
    p = Path(p)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        with gzip.open(str(p) + ".gz", "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _rows(j) -> list[dict]:
    j = j or {}
    f = j.get("fields") or []
    return [dict(zip(f, r)) for r in j.get("rows") or []]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def club_code(name: str) -> str:
    known = CLUB_CODES.get(name)
    if known:
        return known
    s = "".join(ch for ch in unicodedata.normalize("NFD", str(name or "")) if not unicodedata.combining(ch))
    s = "".join(ch for ch in s if ch.isalnum() or ch in " -")
    words = [w for w in s.replace("-", " ").split() if w and w.lower() not in CODE_SKIP]
    if not words:
        return str(name or "")[:3].upper()
    c = words[0][:3] if len(words) == 1 else (words[0][0] + words[1][:2] if len(words) == 2 else "".join(w[0] for w in words[:3]))
    return c.upper()


def short_name(name: str) -> str | None:
    """A shorter name for tight spots, or None when the full one is short enough or nothing obvious shortens it."""
    if name in SHORT:
        return SHORT[name]
    if len(name) <= 12:
        return None
    for p in SHORT_PREFIX:
        if name.startswith(p) and len(name) > len(p) + 2:
            return name[len(p):]
    return None


def _day(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def snapshots(elo_history: dict) -> tuple[list[dict], dict]:
    """[{key, label, date}] (oldest first, the last one "Now") and {team: [Elo at each snapshot, None before its first
    game]}: seven days apart counting back from the latest league game, a week without a game left out."""
    hist = {}
    for t, entries in (elo_history or {}).items():
        pts = [(_day(h.get("date")), PW.num(h.get("elo"))) for h in entries or [] if isinstance(h, dict)]
        hist[t] = sorted(((d0, v) for d0, v in pts if d0 is not None and v is not None), key=lambda x: x[0])
    days = sorted({d0 for h in hist.values() for d0, _v in h})
    if not days:
        return [], {}
    cuts, d = [], days[-1]
    while d >= days[0] and len(cuts) < 60:
        cuts.append(d)
        d -= timedelta(days=STEP_DAYS)
    cuts.reverse()
    keep, prev = [], None
    for c in cuts:
        if prev is None or any(prev < x <= c for x in days):
            keep.append(c)
        prev = c
    keep = keep[-PW.MAX_SNAPSHOTS:]

    def at(h, c):
        v = None
        for d0, x in h:
            if d0 > c:
                break
            v = x
        return v
    paths = {t: [at(h, c) for c in keep] for t, h in hist.items()}
    snaps = [{"key": c.isoformat(), "label": f"{c.day} {c.strftime('%b')}", "date": c.isoformat()} for c in keep]
    snaps[-1]["label"] = "Now"
    return snaps, paths


def _table_rows(slug: str, kind: str, data: Path, tb: dict) -> tuple[dict, str, bool]:
    """{team: row with _group, _of} from the table the site shows for this league's games, the label for its stat cell,
    and whether it is one table holding every club (so its place compares with the power rank)."""
    out, label, single = {}, "Table", False
    groups = []
    if kind == "liga":
        z = _read(data / slug / "zones.json") or {}
        for k, v in sorted((z.get("zones") or {}).items()):
            groups.append((f"Zone {k}", (v or {}).get("standings") or []))
        label = "Clausura" if str(z.get("tournament") or "") == "clausura" else "Table"
    elif tb.get("conferences"):
        for k, rs in tb["conferences"].items():
            groups.append((str(k), rs or []))
    elif tb.get("standings"):
        groups.append(("", tb["standings"]))
        single = True
        st = tb.get("stage") or {}
        if kind == "torneo" and st.get("label"):
            label = str(st["label"])
    for g, rs in groups:
        for r in rs:
            if r.get("team") and r["team"] not in out:
                out[r["team"]] = dict(r, _group=g, _of=len(rs))
    return out, label, single


def _place(r: dict) -> str | None:
    pos, pts = r.get("pos"), PW.num(r.get("pts"))
    if not pos or pts is None:
        return None
    g = r.get("_group") or ""
    where = f" in the {g[:4]}" if g in ("Eastern", "Western") else (f" in {g}" if g else "")
    return f"{PW.ordinal(pos)}{where}, {int(pts)} pt{'' if int(pts) == 1 else 's'}"


def _record(r: dict) -> str | None:
    if PW.num(r.get("w")) is None or PW.num(r.get("l")) is None:
        return None
    return f"W{int(r['w'])} D{int(r.get('d') or 0)} L{int(r['l'])}"


def _signed(v, d: int = 2) -> str:
    return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v):.{d}f}"


def _phase(c: dict, probs: list[dict], chance_key: str) -> str:
    cur = c.get("current_season") or {}
    if cur.get("status") and cur.get("status") != "current":
        return "offseason"
    gp, gt = PW.num(c.get("games_played")), PW.num(c.get("games_total"))
    if gp is not None and gt and gp >= gt:
        live = any(0.0005 < (PW.num(r.get(chance_key)) or 0) < 0.9995 for r in probs)
        return "postseason" if live else "offseason"
    return "season"


def _season_label(c: dict) -> tuple:
    cur = c.get("current_season") or {}
    s, era = str(cur.get("season") or ""), str(cur.get("era") or "")
    if any(ch.isalpha() for ch in s):
        return era or s, s                                  # "Apertura 2026", "Clausura 2026"
    return era or s, f"{era or s} season"


def _covered(pool: list[dict], key: str) -> bool:
    """A rate the source covers in this league: not zero for nine players in ten (Uruguay, Chile and Peru have no
    post-shot xG, so every keeper's goals prevented reads 0.00 there: the column is left out, not shown as zeros)."""
    xs = [PW.num((r.get("v") or {}).get(key)) for r in pool]
    xs = [x for x in xs if x is not None]
    return bool(xs) and sum(1 for x in xs if x == 0) < 0.9 * len(xs)


def _players(slug: str, data: Path, colour: dict) -> dict | None:
    lab = _read(data / "lab" / "season" / f"{slug}.json")
    rows = _rows(lab)
    if not rows:
        return None
    floor = PW.num((lab or {}).get("floor")) or 0
    groups = []
    for key, label, short, roles, mins, stats in GROUPS:
        need = max(mins, floor)
        pool = []
        for r in rows:
            if r.get("role") not in roles or (PW.num(r.get("minutes")) or 0) < need:
                continue
            v = {k: r.get(k) for k in [METRIC["key"]] + [s[0] for s in stats] if k in r}
            m = PW.num(r.get("minutes")) or 0
            for k, src in TOTALS.items():
                x = PW.num(r.get(src))
                v[k] = (round(x * m / 90) if k != "xg" else round(x * m / 90, 2)) if x is not None else None
            v["minutes"] = m
            tm = r.get("team") or ""
            pool.append({"id": str(r.get("player_id")), "name": r.get("name"), "team": club_code(tm),
                         "colour": colour.get(str(r.get("tid"))), "href": f"#/player/{r.get('player_id')}?c={slug}",
                         "sub": r.get("role") if len(roles) > 1 else None, "v": v})
        st = [{"key": k, "label": lab_, "fmt": f, "tip": tip} for k, lab_, f, tip in stats if k in TOTALS or k == "minutes" or _covered(pool, k)]
        g = PW.group(key, label, pool, METRIC, st, short=short,
                     min_text=f"{int(need)}+ league minutes this season, in the formation role started most")
        if g:
            groups.append(g)
    return {"noun": "players", "groups": groups} if groups else None


def league_doc(c: dict, data: Path, colour: dict, now: str | None = None) -> dict | None:
    slug, kind = c["slug"], c.get("kind")
    st = _read(data / slug / "strength.json") or {}
    snaps, paths = snapshots(st.get("elo_history") or {})
    if not snaps:
        return None
    srows = {r.get("team"): r for r in st.get("rows") or [] if r.get("team")}
    tm = (_read(data / slug / "teams.json") or {}).get("teams") or {}
    tid = {nm: str(v.get("team_id")) for nm, v in tm.items() if isinstance(v, dict) and v.get("team_id") is not None}
    tb = _read(data / slug / "table.json") or {}
    trow, tlabel, single = _table_rows(slug, kind, data, tb)
    pr = _read(data / slug / "probs.json") or {}
    probs = pr.get("teams") or []
    prow = {r.get("team"): r for r in probs if r.get("team")}
    chance_key = "p_cup" if kind in ("conference", "playoff") else "p_title"
    fav = str(c.get("favourite_label") or "Title")
    chance_label = "Title" if fav in ("Title", "Winner", "Champion") or fav.endswith(" champion") else fav
    phase = _phase(c, probs, chance_key)
    teams = [t for t in paths if t in srows or t in tid]
    now_vals = [paths[t][-1] for t in teams if paths[t][-1] is not None]
    if not now_vals:
        return None
    mean = sum(now_vals) / len(now_vals)
    # the power rank now, for the "Nth in the table" clause
    order = sorted((t for t in teams if paths[t][-1] is not None), key=lambda t: -paths[t][-1])
    prank = {t: i + 1 for i, t in enumerate(order)}
    won = None
    if kind == "league" and single:
        from oddsmarkets.football.analytics.follow_build import clinched_first
        complete = bool(tb.get("total_games")) and tb.get("games_played") == tb.get("total_games")
        lead = clinched_first(tb.get("standings"), tb.get("matches_per_team"), complete)
        won = (lead or {}).get("team")
    ents, extra = [], {}
    for t in teams:
        s, r, p = srows.get(t) or {}, trow.get(t) or {}, prow.get(t) or {}
        ident = tid.get(t) or t
        played = PW.num(s.get("played"))
        ent = {"id": ident, "name": t, "short": short_name(t), "abbr": club_code(t), "colour": colour.get(tid.get(t, "")),
               "href": f"#/club/{tid[t]}?c={slug}" if t in tid else None,
               "group": (f"{s['conference']} Conference" if s.get("conference") in ("Eastern", "Western") else
                         (f"Zone {s['zone']}" if s.get("zone") else None)),
               "rpath": [None if v is None else v - mean for v in paths[t]],
               "record": _record(r), "form": "".join(x for x in (s.get("form_results") or []) if x in "WDL") or None}
        pc = PW.num(p.get(chance_key))
        if phase in ("season", "postseason") and pc is not None and 0.0005 <= pc < 0.9995 and t != won:
            ent["chance"] = {"label": chance_label, "p": round(pc, 4)}
        cells = []
        if _place(r):
            cells.append({"label": tlabel, "text": _place(r)})
        if PW.num(s.get("strength_ppg")) is not None:
            cells.append({"label": "Points rating", "text": f"{float(s['strength_ppg']):.2f} a game"})
        if PW.num(s.get("xg_diff")) is not None and played:
            cells.append({"label": "xG diff", "text": _signed(float(s["xg_diff"]) / played) + " a game"})
        if cells:
            ent["stats"] = cells[:3]
        x = []
        if t == won:
            x.append("Champions: the title is won")
        if single and r.get("pos") and t in prank and abs(int(r["pos"]) - prank[t]) >= 4:
            x.append(f"{PW.ordinal(r['pos'])} in the table")
        if x:
            extra[ident] = x
        ents.append(ent)
    rows = PW.teams_block(ents, snaps, step="week", rating_fmt="+0", extra_notes=extra)
    for t in rows:                                   # "won 5 straight; title chance 21%", not "; Title chance"
        if t.get("note"):
            t["note"] = t["note"].replace("; Title chance", "; title chance")
    era, season_label = _season_label(c)
    upd = now or st.get("updated_at") or _now()
    label = LABEL.get(slug) or c.get("name") or slug
    players = _players(slug, data, colour)
    notes = ["Ranked on our Elo rating, replayed over this season's league games from where each club finished last season: "
             "a result moves it, and a win over a stronger side moves it more. Each snapshot counts the league games up to "
             "its date; they are a week apart, counted back from the latest game." +
             (" Play-off games are not in it: the ranking stands where the league season ended." if phase == "postseason" else ""),
             "The points rating beside it is the model the Teams pages rank on (the points a game we expect against an "
             "average side); it has no game-by-game history, so the weekly ranking cannot use it.",
             "Players: this season's league games, qualified by minutes in the formation role started most (the rule is "
             "under each group). GAR/90 is our value model's goals added per 90 over a replacement-level player in the same role."]
    return PW.document(site=SITE, sport=SPORT, league=slug, label=label, season=era, season_label=season_label,
                       updated_at=upd, asof=str(snaps[-1]["date"]), phase=phase,
                       rating={"label": "Our rating", "short": "Elo", "unit": "Elo points above the league's average club", "fmt": "+0",
                               "tip": "Our Elo rating over this season's league games, against the league's average club. "
                                      "A side 100 points above another has about a 64% expected score against it on a "
                                      "neutral ground (a win counts 1, a draw a half)."},
                       snapshots=snaps, teams=rows, step="week", kind="teams", noun="clubs", players=players, notes=notes)


def build(data_root: Path, now: str | None = None) -> dict | None:
    data = Path(data_root)
    comps = (_read(data / "competitions.json") or {}).get("competitions") or []
    leagues = [c for c in comps if c.get("slug") and c.get("ok") and c.get("kind") in LEAGUE_KINDS]
    if not leagues:
        return None
    colour = {}
    for r in _rows(_read(data / "clubs_index.json")):
        c = r.get("colour")
        if isinstance(c, str) and len(c.lstrip("#")) == 6:
            colour[str(r.get("id"))] = c if c.startswith("#") else "#" + c
    docs = []
    for c in leagues:
        try:
            d = league_doc(c, data, colour, now)
        except Exception as exc:  # noqa: BLE001  (one league failing never takes the others down)
            log.error("power rankings: %s skipped: %r", c.get("slug"), exc)
            continue
        if d:
            docs.append(d)
    if not docs:
        return None
    return PW.write(data, docs, site=SITE, sport=SPORT, updated_at=now or _now(), default=DEFAULT)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "docs" / "site" / "data"
    print(build(root))
