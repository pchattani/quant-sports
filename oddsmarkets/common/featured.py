"""
Which game leads a page, and the "Today / This week" digest: sport-agnostic, shared by the Home builder
(scripts/build_home.py) and the sport sites' overview builders.

Why this exists. The Home page used to lead with whatever game the front end's closeness score liked best, so a
50/50 WTA 250 match at 03:00 sat at the top labelled "Our pick tonight". A game now leads only on a
**significance score**: how big the competition is, how far into it we are, what rides on it in our own
simulations, and whether it is on at a sane hour soon. Closeness is a small bonus, never the main criterion.

Everything here is stdlib and works on plain dicts, so any builder can call it without importing a sport.

The game dict
-------------
The Home page's normalised game (build_home.game) is the input format. The fields read are:

    sport      "football" | "nfl" | "basketball" | "baseball" | "hockey" | "tennis" | "f1" | "college"
    league     display league, e.g. "NFL", "NBA", "WNBA", "MLB", "NHL", "CFB", "MBB", "WBB", "ATP · Shanghai"
    start      ISO 8601 UTC ("2026-10-24T19:00:00Z")
    status     "pre" | "live" | "final" | "off"
    p_home, p_draw, p_away      our pre-game chances (p_away defaults to 1 - p_home - p_draw)
    wp_home    our live chance, if any
    note       free text the site already shows ("ALCS · G7", "Week 7", "SF")
    event      True for a race (F1): one entrant field, no two sides

plus an optional `sig` dict of hints only the sport builder knows (every key optional):

    comp       a competition key for the tier table (football slug "premier-league"; tennis level "slam",
               "finals", "m1000", "500", "250", "other", "challenger")
    stage      "final" | "semi" | "quarter" | "playoff" | "knockout" | "league"; finer stage words are mapped
    round      a raw round label ("F", "SF", "QF", "sf", "final", "r16") when stage is unknown
    series     {"game": n, "wins": [a, b], "best_of": 7, "name": "World Series"} for a playoff series
    preseason  True for exhibition games (NBA/NHL/NFL preseason): heavily discounted
    ranks      [home rank, away rank] (college polls; None for unranked)
    title      [home p, away p]: each side's chance of the title / championship in our simulation
    playoff    [home p, away p]: each side's chance of making the playoffs in our simulation
    rivalry    a name ("North London derby") when the fixture is a known rivalry (see RIVALRIES)

API
---
    significance(g, now) -> {"score": float, "parts": {tier, stage, stakes, timing, hour, close, live},
                             "reasons": [plain-English strings], "hours": float | None}
        The score is a sum of parts (rough scale: 0 = nothing, 40 = a normal big-league game, 70+ = a final).
        The parts and their ranges:
          tier    0-50   the competition (TIERS; preseason x0.4)
          stage   0-40   finals, semis, playoffs, Game 7s, elimination games, ranked v ranked, rivalries
          stakes  0-20   our own sims: title chance in play (4p(1-p), largest side), a meeting of two title
                         contenders, or a playoff place in the balance. A proxy for "how much the result moves
                         the race": the sims hold no conditional runs, so it reads uncertainty, not a delta.
          timing  -15-+14  live now +14; starting in 0-18 h: +10 falling 0.3 per hour; later than that -15
          hour    -18 or 0  a start between 12:00 and 23:45 in UTC-5 or UTC+1 (the main audience, New York to
                         Paris) is fine; otherwise -18 (a 03:00 London / 22:00 New York start is still fine)
          close   0-6    6 x (1 - |favourite - underdog|): a small bonus, never the deciding part
    rank_featured(games, now, horizon_h=18, min_score=30, limit=5) -> {"today": [row...], "week": row | None}
        `today`: playable games (not final, not off, not a stale "pre" 3 h past its start) starting within
        horizon_h hours or live, scoring at least min_score, best first. `week`: the best game or event in the
        next 7 days by tier + stage + stakes alone (the fallback when nothing big is on today). Each row is
        {"key": "<sport>:<id>", "score", "reasons", "label_hint"}. A front end then takes the first row whose
        game is still upcoming or live at the viewer's clock, else `week`, else a title race.
    when_label(start, now, tz_minutes=0, live=False) -> "Live now" | "Tonight · 20:00" | "Today · 14:00" |
                                                        "Tomorrow · 03:00" | "Sat · 18:30" | "Sat 31 Oct"
        "Tonight" only for a start later today at 17:00 or after in that zone. Browsers should do this with the
        viewer's own zone (docs/home/assets/home.js `whenTag`); this is the same rule for Python callers.
        Never "Our pick".

    Digest helpers (no look-ahead: they take finished games with the chance that was published BEFORE the
    start; a caller must pass only sports whose finished-game chances are frozen or computed as of the day
    before, and say which sports it left out):
    favourites_record(games, now, days=7) -> {"n", "won", "expected", "from", "to", "by": [{sport, n, won,
                                               expected}]} | None
        "Favourites won 31 of 44 (70%); we expected 68%": expected is the mean of the favourites' chances, the
        number of wins a calibrated forecaster expects. Draws count as a favourite not winning (football's
        three-way chances), ties with no winner are skipped.
    upset_of_week(games, now, days=7) -> {"game": g, "p": winner's pre-game chance} | None
        The final whose winner we gave the lowest pre-game chance.
    biggest_swing(series, now, days=7, min_move=0.03) -> {"name", "league", "kind", "from", "to", "delta",
                                                         "since", "href"} | None
        series: [{"name", "league", "kind": "title" | "playoff", "points": [[iso_ts, p], ...], "href"}].
        The largest absolute move from the first point at or after now - days (or the earliest point there is,
        and `since` says when) to the latest point at or before now.

Tier tables are deliberately plain numbers in one place (TIERS) so a sport builder can read or extend them.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

# ───────────────────────────────────────────────────────────── tiers (0-50)
TIERS: dict[str, dict[str, float]] = {
    "nfl": {"*": 46},
    "basketball": {"NBA": 40, "WNBA": 30, "*": 28},
    "baseball": {"MLB": 30, "*": 14},             # the postseason adds its stage below
    "hockey": {"NHL": 34, "*": 14},
    "f1": {"*": 42},                              # a Grand Prix
    "college": {"CFB": 30, "MBB": 20, "WBB": 16, "*": 14},
    "tennis": {"slam": 44, "finals": 38, "m1000": 28, "500": 18, "250": 10, "other": 6, "challenger": 4,
               "itf": 2, "*": 10},
    "football": {
        "world-cup": 50, "euro": 48, "champions-league": 45, "premier-league": 44, "copa-america": 42,
        "la-liga": 40, "serie-a": 38, "bundesliga": 38, "libertadores": 34, "club-world-cup": 34,
        "ligue-1": 33, "europa-league": 32, "wc-qual-uefa": 30, "wc-qual-conmebol": 30, "nations-league": 28,
        "fa-cup": 28, "brasileirao": 28, "mls": 26, "conference-league": 24, "eredivisie": 24,
        "primeira-liga": 24, "liga-mx": 24, "copa-del-rey": 24, "dfb-pokal": 24, "coppa-italia": 22,
        "sudamericana": 22, "afcon": 30, "gold-cup": 24, "asian-cup": 24, "coupe-de-france": 20, "efl-cup": 20,
        "saudi-pro-league": 20, "liga-argentina": 20, "uefa-super-cup": 24, "community-shield": 16,
        "supercopa-espana": 20, "wc-qual-caf": 18, "wc-qual-afc": 18, "wc-qual-concacaf": 18,
        "euro-qualifiers": 24, "friendlies": 6, "*": 14,
    },
}
PRESEASON_FACTOR = 0.4

STAGE_POINTS = {"final": 28, "semi": 16, "quarter": 9, "playoff": 8, "knockout": 6, "league": 0}
# A championship series or the one-game final of a big league is worth more than a cup final of a minor one: the
# stage points scale with the tier (a 50-tier final gets the full amount, a 14-tier one about 60%).

# Known rivalries, by sorted pair of the names the sites use (football: Sofascore club names). Kept short and
# hand-checked: a derby the table does not know just scores as a normal game.
RIVALRIES = {
    frozenset(("Arsenal", "Tottenham")): "North London derby",
    frozenset(("Manchester United", "Manchester City")): "Manchester derby",
    frozenset(("Liverpool", "Everton")): "Merseyside derby",
    frozenset(("Liverpool", "Manchester United")): "Liverpool v Manchester United",
    frozenset(("Real Madrid", "Barcelona")): "El Clásico",
    frozenset(("Real Madrid", "Atlético Madrid")): "Madrid derby",
    frozenset(("Inter", "Milan")): "Derby della Madonnina",
    frozenset(("Roma", "Lazio")): "Derby della Capitale",
    frozenset(("Juventus", "Inter")): "Derby d'Italia",
    frozenset(("Borussia Dortmund", "Bayern München")): "Der Klassiker",
    frozenset(("Borussia Dortmund", "Schalke 04")): "Revierderby",
    frozenset(("Paris Saint-Germain", "Marseille")): "Le Classique",
    frozenset(("Ajax", "Feyenoord")): "De Klassieker",
    frozenset(("Benfica", "Porto")): "O Clássico",
    frozenset(("Celtic", "Rangers")): "Old Firm derby",
    frozenset(("Boca Juniors", "River Plate")): "Superclásico",
    frozenset(("Flamengo", "Fluminense")): "Fla-Flu",
    frozenset(("Galatasaray", "Fenerbahçe")): "Intercontinental derby",
    frozenset(("América", "Guadalajara")): "El Súper Clásico",
    # US leagues (nicknames as the Home page prints them)
    frozenset(("Yankees", "Red Sox")): "Yankees v Red Sox",
    frozenset(("Dodgers", "Giants")): "Dodgers v Giants",
    frozenset(("Celtics", "Lakers")): "Celtics v Lakers",
    frozenset(("Bears", "Packers")): "Bears v Packers",
    frozenset(("Cowboys", "Eagles")): "Cowboys v Eagles",
    frozenset(("Canadiens", "Maple Leafs")): "Canadiens v Maple Leafs",
    frozenset(("Ohio State", "Michigan")): "The Game",
    frozenset(("Alabama", "Auburn")): "The Iron Bowl",
}

AUDIENCE_ZONES = (-5, 1)          # New York (EST) to Paris (CET): the main audience
GOOD_HOURS = (12.0, 23.75)        # a start in this local window, in either zone, is a sane hour


def parse_ts(s):
    """ISO 8601 -> aware UTC datetime; a bare date is midnight UTC; None when unreadable."""
    if not s:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
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


def _f(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def two_way(g):
    """(p_home, p_away, p_draw) from our pre-game numbers, or None."""
    ph = _f(g.get("p_home"))
    if ph is None:
        return None
    pd = _f(g.get("p_draw")) or 0.0
    pa = _f(g.get("p_away"))
    if pa is None:
        pa = max(0.0, 1.0 - ph - pd)
    return ph, pa, pd


# ───────────────────────────────────────────────────────────── the parts
def tier_points(g):
    sig = g.get("sig") or {}
    table = TIERS.get(g.get("sport")) or {"*": 14}
    key = sig.get("comp")
    if key is None:
        lg = str(g.get("league") or "")
        key = lg if lg in table else lg.split(" ")[0]
    t = table.get(key, table.get("*", 14))
    if sig.get("preseason"):
        t *= PRESEASON_FACTOR
    return float(t)


_ROUND_STAGE = {
    "f": "final", "final": "final", "finals": "final", "sf": "semi", "semi": "semi", "semifinal": "semi",
    "semi-final": "semi", "semi-finals": "semi", "qf": "quarter", "quarter": "quarter", "quarterfinal": "quarter",
    "quarter-final": "quarter", "quarter-finals": "quarter", "r16": "knockout", "r32": "knockout",
    "round of 16": "knockout", "playoff": "playoff", "playoffs": "playoff", "knockout": "knockout",
}


def stage_of(g):
    """'final' | 'semi' | 'quarter' | 'playoff' | 'knockout' | 'league' | None from sig.stage / sig.round / note."""
    sig = g.get("sig") or {}
    st = sig.get("stage")
    if st in STAGE_POINTS:
        return st
    for raw in (sig.get("round"), st):
        if raw is not None:
            k = str(raw).strip().lower()
            if k in _ROUND_STAGE:
                return _ROUND_STAGE[k]
    return None


def stage_points(g):
    """(points, reasons) for the stage: finals, semis, series deciders, ranked match-ups, rivalries."""
    sig = g.get("sig") or {}
    pts, why = 0.0, []
    st = stage_of(g)
    scale = 0.6 + 0.4 * min(1.0, tier_points(g) / 50.0)
    if st and STAGE_POINTS.get(st):
        pts += STAGE_POINTS[st] * scale
        why.append({"final": "a final", "semi": "a semi-final", "quarter": "a quarter-final",
                    "playoff": "a play-off", "knockout": "a knockout tie"}[st])
    ser = sig.get("series") or {}
    if ser:
        n = ser.get("game")
        best = ser.get("best_of") or 7
        wins = ser.get("wins") or []
        need = best // 2 + 1
        if isinstance(n, int) and n == best:
            pts += 20
            why.append(f"Game {n}: winner takes the series")
        elif len(wins) == 2 and max(wins) == need - 1:
            pts += 10
            why.append("one side can close out the series")
        if ser.get("name") and not st:
            nm = str(ser["name"])
            pts += 26 if any(w in nm for w in ("World Series", "Stanley Cup Final", "NBA Finals", "WNBA Finals",
                                              "Super Bowl")) else 12
            why.append(nm)
    ranks = [r for r in (sig.get("ranks") or []) if isinstance(r, int) and 0 < r <= 25]
    if len(ranks) == 2:
        pts += 14 if max(ranks) <= 10 else 8
        why.append(f"#{ranks[0]} v #{ranks[1]}")
    elif len(ranks) == 1:
        pts += 3
    if sig.get("rivalry"):
        pts += 10
        why.append(str(sig["rivalry"]))
    return min(40.0, pts), why


def stakes_points(g):
    """(points, reasons) from our simulations: a title chance in play, two contenders meeting, a playoff place."""
    sig = g.get("sig") or {}
    pts, why = 0.0, []
    title = [p for p in (_f(x) for x in (sig.get("title") or [])) if p is not None]
    if title:
        lev = max(4 * p * (1 - p) for p in title)
        pts += 14 * lev
        if len(title) == 2 and min(title) >= 0.1:
            pts += 6
            why.append("two title contenders")
        elif max(title) >= 0.1:
            why.append("a title chance on the line")
    po = [p for p in (_f(x) for x in (sig.get("playoff") or [])) if p is not None]
    if po:
        lev = max(4 * p * (1 - p) for p in po)
        pts += 8 * lev
        if lev >= 0.6:
            why.append("a play-off place in the balance")
    return min(20.0, pts), why


def in_good_hour(start):
    """True when the start is between 12:00 and 23:45 local in UTC-5 or UTC+1."""
    d = parse_ts(start)
    if d is None:
        return False
    for off in AUDIENCE_ZONES:
        loc = d + timedelta(hours=off)
        h = loc.hour + loc.minute / 60.0
        if GOOD_HOURS[0] <= h < GOOD_HOURS[1]:
            return True
    return False


def hours_to(g, now):
    d = parse_ts(g.get("start"))
    return None if d is None else (d - now).total_seconds() / 3600.0


def closeness_points(g):
    live = g.get("status") == "live" and _f(g.get("wp_home")) is not None
    if live:
        ph = _f(g["wp_home"])
        return 6.0 * (1 - abs(ph - (1 - ph)))
    tw = two_way(g)
    if not tw:
        return 0.0
    ph, pa, _ = tw
    return 6.0 * max(0.0, 1 - abs(ph - pa))


def significance(g, now):
    """The significance score of one game (see the module docstring for the parts)."""
    tier = tier_points(g)
    stage, why_stage = stage_points(g)
    stakes, why_stakes = stakes_points(g)
    h = hours_to(g, now)
    live = g.get("status") == "live"
    if live:
        timing = 14.0
    elif h is None:
        timing = -15.0
    elif -3 <= h <= 18:
        timing = 10.0 - 0.3 * max(0.0, h)
    else:
        timing = -15.0
    hour = 0.0 if live or in_good_hour(g.get("start")) else -18.0
    close = closeness_points(g)
    parts = {"tier": round(tier, 1), "stage": round(stage, 1), "stakes": round(stakes, 1),
             "timing": round(timing, 1), "hour": hour, "close": round(close, 1), "live": live}
    score = tier + stage + stakes + timing + hour + close
    return {"score": round(score, 1), "parts": parts, "reasons": why_stage + why_stakes,
            "hours": None if h is None else round(h, 1)}


def _playable(g, now):
    if g.get("status") in ("final", "off"):
        return False
    h = hours_to(g, now)
    if g.get("status") == "pre" and (h is None or h < -3):
        return False                       # a "pre" game well past its start is a stale input
    if g.get("status") == "live" and h is not None and h < -8:
        return False
    return True


def game_key(g):
    return f"{g.get('sport')}:{g.get('id')}"


def rank_featured(games, now, horizon_h=18, min_score=30, limit=5):
    """{"today": [up to `limit` rows, best first], "week": the best of the next 7 days | None}.

    today: live, or starting within horizon_h hours; score >= min_score. week: tier + stage + stakes only (the
    biggest occasion of the week, whatever the hour), for when today has nothing big."""
    today, week = [], []
    for g in games:
        if not _playable(g, now):
            continue
        s = significance(g, now)
        h = s["hours"]
        row = {"key": game_key(g), "score": s["score"], "reasons": s["reasons"], "parts": s["parts"]}
        if g.get("status") == "live" or (h is not None and h <= horizon_h):
            if s["score"] >= min_score:
                today.append(row)
        if h is not None and h <= 7 * 24 or g.get("status") == "live":
            p = s["parts"]
            week.append(dict(row, week_score=round(p["tier"] + p["stage"] + p["stakes"], 1)))
    today.sort(key=lambda r: -r["score"])
    week.sort(key=lambda r: -r["week_score"])
    best_week = week[0] if week else None
    return {"today": today[:limit], "week": best_week}


# ───────────────────────────────────────────────────────────── labels
WEEKDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTH = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def when_label(start, now, tz_minutes=0, live=False):
    """The en-GB, 24-hour label for a start in a zone tz_minutes east of UTC. "Tonight" only for a start later
    today at 17:00 or after; "Today" for earlier today; "Tomorrow"; the weekday within 6 days; else the date."""
    if live:
        return "Live now"
    d = parse_ts(start)
    if d is None:
        return ""
    off = timedelta(minutes=tz_minutes)
    loc, ln = d + off, now + off
    hm = f"{loc.hour:02d}:{loc.minute:02d}"
    days = (loc.date() - ln.date()).days
    if days == 0:
        return ("Tonight · " if loc.hour >= 17 else "Today · ") + hm
    if days == 1:
        return "Tomorrow · " + hm
    if 1 < days < 7:
        return f"{WEEKDAY[loc.weekday()]} · {hm}"
    return f"{WEEKDAY[loc.weekday()]} {loc.day} {MONTH[loc.month - 1]}"


# ───────────────────────────────────────────────────────────── digest
def _result(g):
    """(favourite won: bool, favourite's chance, winner's chance) for a final with our pre-game chances; None
    when there is no pre-game chance or no winner (a draw counts as the favourite not winning)."""
    if g.get("status") != "final" or g.get("event"):
        return None
    tw = two_way(g)
    hs, as_ = _f(g.get("hs")), _f(g.get("as"))
    if not tw or hs is None or as_ is None:
        return None
    ph, pa, pd = tw
    fav_home = ph >= pa
    pf = ph if fav_home else pa
    if hs == as_:
        if pd > 0:
            return False, pf, pd
        return None
    home_won = hs > as_
    return (home_won == fav_home), pf, (ph if home_won else pa)


def _recent(games, now, days):
    lo = now - timedelta(days=days)
    for g in games:
        d = parse_ts(g.get("start"))
        if d is not None and lo <= d <= now:
            yield g, d


def favourites_record(games, now, days=7):
    """How our favourites did on finished games that started in the last `days` days (module docstring)."""
    rows = []
    for g, d in _recent(games, now, days):
        r = _result(g)
        if r is None:
            continue
        fav_won, pf, _ = r
        if abs(pf - 0.5) < 1e-9:
            continue                        # a dead 50/50 has no favourite
        rows.append((g.get("sport"), fav_won, pf, d))
    if not rows:
        return None
    by = {}
    for sp, won, pf, _ in rows:
        b = by.setdefault(sp, {"sport": sp, "n": 0, "won": 0, "exp": 0.0})
        b["n"] += 1
        b["won"] += 1 if won else 0
        b["exp"] += pf
    n = len(rows)
    return {"n": n, "won": sum(1 for r in rows if r[1]), "expected": round(sum(r[2] for r in rows) / n, 4),
            "from": min(r[3] for r in rows).strftime("%Y-%m-%d"), "to": max(r[3] for r in rows).strftime("%Y-%m-%d"),
            "by": [{"sport": b["sport"], "n": b["n"], "won": b["won"], "expected": round(b["exp"] / b["n"], 4)}
                   for b in sorted(by.values(), key=lambda b: -b["n"])]}


def upset_of_week(games, now, days=7, max_p=0.4):
    """The final in the last `days` days whose winner had the lowest pre-game chance (at most max_p)."""
    best = None
    for g, _ in _recent(games, now, days):
        r = _result(g)
        if r is None or r[0]:
            continue
        hs, as_ = _f(g.get("hs")), _f(g.get("as"))
        if hs == as_:
            continue                        # a draw is a surprise, not an upset winner
        pw = r[2]
        if pw <= max_p and (best is None or pw < best["p"]):
            best = {"game": g, "p": round(pw, 4)}
    return best


def biggest_swing(series, now, days=7, min_move=0.03):
    """The largest move in a title / playoff chance over the last `days` days (module docstring)."""
    lo = now - timedelta(days=days)
    best = None
    for s in series or []:
        pts = []
        for ts, p in s.get("points") or []:
            d, p = parse_ts(ts), _f(p)
            if d is not None and p is not None and d <= now:
                pts.append((d, p))
        if len(pts) < 2:
            continue
        pts.sort()
        inside = [x for x in pts if x[0] >= lo]
        first = inside[0] if inside else None
        if first is None or first == pts[-1]:
            continue
        last = pts[-1]
        delta = last[1] - first[1]
        if abs(delta) >= min_move and (best is None or abs(delta) > abs(best["delta"])):
            best = {"name": s.get("name"), "league": s.get("league"), "kind": s.get("kind") or "title",
                    "from": round(first[1], 4), "to": round(last[1], 4), "delta": round(delta, 4),
                    "since": first[0].strftime("%Y-%m-%dT%H:%M:%SZ"), "href": s.get("href"),
                    "sport": s.get("sport")}
    return best
