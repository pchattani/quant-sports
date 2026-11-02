"""The Campus's follow cards (My Teams): one small card per team at data/follow/<level>/<id>.json, for college football,
men's and women's basketball and men's and women's hockey (cfb, mbb, wbb, mch, wch).

The schema and the fact engine are oddsmarkets/common/follow.py. Each team's own payload, <L>/<S>/teams/<id>.json, is
already close to a card; this module trims it and adds what needs the whole level (ranks, the chance changes, the
significance of the next game). It reads only what the Campus build has written (no new fetching):

    index.json                    each level's current season and phase, its teams (names, colours, conferences)
    <L>/<S>/season.json           conferences (names), standings (the conference place), the power order, rating
                                  paths (our rank a month ago), polls (the AP / USCHO rank), the season simulation
    <L>/<S>/teams/<id>.json       record, rating, schedule (results with the chance frozen before the game, and the
                                  games to come), stats with their league ranks, strengths and needs, the top players
    <L>/<S>/teams.json            the team metric spec (labels, direction, format)
    <L>/race_log.json, chance_log.json   our playoff / tournament and title chances by day (the 7-day change)
    <L>/history.json              champions (a decided season's champion)

    build(data_root, level, now=None) -> {"n", "bytes", "max", "ids"}         (python -m oddsmarkets.college.follow_build)

Size: about 1.7-2.6 KB a card, about 2.3 MB for the five levels' ~975 teams (the site is about 385 MB).

No look-ahead: a result counts only once its start is at or before the build clock, a finished game's chance is the
schedule's chance from before the game, a 7-day change compares two log snapshots taken on those days, and our rank a
month ago is the rating path at that date.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL

log = logging.getLogger(__name__)

SITE, SPORT = "campus", "college"
LEVELS = ("cfb", "mbb", "wbb", "mch", "wch")
HOCKEY = ("mch", "wch")
LEVEL_LABEL = {"cfb": "College football", "mbb": "Men’s basketball", "wbb": "Women’s basketball", "mch": "Men’s hockey", "wch": "Women’s hockey"}
POOL = {"cfb": "FBS", "mbb": "Division I", "wbb": "Division I", "mch": "Division I", "wch": "Division I"}
LEAGUE_WHERE = {"cfb": "FBS", "mbb": "Division I", "wbb": "Division I", "mch": "Division I", "wch": "Division I"}
# the playoff / tournament place, then the title (the card's headline is the last one shown)
FIELD = {"cfb": ("p_cfp", "Playoff"), "mbb": ("p_ncaa", "NCAA tournament"), "wbb": ("p_ncaa", "NCAA tournament"),
         "mch": ("p_ncaa", "NCAA tournament"), "wch": ("p_ncaa", "NCAA tournament")}
COUNTS = ("reg", "conf", "cfp", "bowl", "ncaa", "post", "nit", "cbi")      # exhibitions ("exh", "pre") left out
# box-score and model metrics that are not "better or worse" (or have their own fact) stay out of the league-rank fact
NOT_RANKED = {"rating", "sos", "luck", "wpct", "tempo", "pace", "se", "pdo"}
MIN_GAMES = {"cfb": 4, "mbb": 8, "wbb": 8, "mch": 6, "wch": 6}
POS_PLURAL = {
    "cfb": {"QB": "quarterbacks", "RB": "running backs", "WR": "receivers", "TE": "tight ends", "OL": "offensive linemen",
            "DL": "defensive linemen", "LB": "linebackers", "DB": "defensive backs", "K": "kickers", "P": "punters"},
    "mbb": {"G": "guards", "F": "forwards", "C": "centres"}, "wbb": {"G": "guards", "F": "forwards", "C": "centres"},
    "mch": {"F": "forwards", "D": "defencemen", "G": "goalies"}, "wch": {"F": "forwards", "D": "defenders", "G": "goalies"},
}
UK = (("DL/edge", "Defensive front"), ("Defense", "Defence"), ("defense", "defence"), ("Offense", "Offence"), ("offense", "offence"), ("Center", "Centre"))


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


_num = FL._num


def uk(s) -> str:
    s = str(s or "")
    for a, b in UK:
        s = s.replace(a, b)
    return s


def rows_of(x) -> list[dict]:
    """A payload table: a list of dicts, or payload format 2's {"$cols", "$rows"} (dotted columns -> nested dicts)."""
    if isinstance(x, list):
        return [r for r in x if isinstance(r, dict)]
    if not isinstance(x, dict) or "$cols" not in x:
        return []
    cols = x.get("$cols") or []
    out = []
    for r in x.get("$rows") or []:
        d: dict = {}
        for c, v in zip(cols, r):
            if "." in c:
                a, b = c.split(".", 1)
                if v is not None:
                    d.setdefault(a, {})[b] = v
            else:
                d[c] = v
        out.append(d)
    return out


def _fmt(v, f: str | None) -> str:
    v = _num(v)
    if v is None:
        return ""
    if f in ("signed1", "signed2"):
        d = int(f[-1])
        return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v):.{d}f}"
    m = "−" if v < 0 else ""
    a = abs(v)
    if f in ("pct", "prob"):
        return m + f"{a * 100:.1f}%"
    if f == "3":
        return m + (f"{a:.3f}".replace("0.", ".", 1) if a < 1 else f"{a:.3f}")
    if f and f.isdigit():
        return m + f"{a:.{int(f)}f}"
    return m + f"{a:g}"


def _signed(v, d: int = 1) -> str:
    return _fmt(v, f"signed{d}")


def _rank(values: dict, higher: bool = True) -> dict:
    xs = sorted(((v, k) for k, v in values.items() if _num(v) is not None), key=lambda t: -t[0] if higher else t[0])
    out, prev, prev_rank = {}, None, 0
    for i, (v, k) in enumerate(xs, 1):
        r = prev_rank if prev is not None and v == prev else i
        out[k] = r
        prev, prev_rank = v, r
    return out


def _tie_size(rank: dict, k) -> int:
    r = rank.get(k)
    return sum(1 for x in rank.values() if x == r) if r is not None else 0


def phase_of(raw: str | None) -> str:
    r = str(raw or "").lower()
    if r in ("preseason", "pre"):
        return "preseason"
    if r in ("offseason", "complete", "final", "done", "off"):
        return "offseason"
    if any(w in r for w in ("post", "bowl", "cfp", "tourn", "ncaa", "march", "playoff")):
        return "postseason"
    return "season"


def _res_letter(us, them) -> str:
    return "W" if us > them else "L" if us < them else "D"


def results_of(games: list[dict], tid: str, asof: datetime) -> list[dict]:
    """The team's finished games at `asof`, oldest first, as follow.py results (exhibitions left out; a tie is 'D')."""
    out = []
    for g in games:
        if g.get("status") != "post" or g.get("stype") not in COUNTS or tid not in (str(g.get("home")), str(g.get("away"))):
            continue
        t = FL._dt(g.get("date"))
        hs, as_ = _num(g.get("hs")), _num(g.get("as"))
        if t is None or t > asof or hs is None or as_ is None:
            continue
        home = str(g.get("home")) == tid
        us, them = (hs, as_) if home else (as_, hs)
        p = _num((g.get("model") or {}).get("p_home"))
        pa = _num((g.get("model") or {}).get("p_away"))
        pw = None if p is None else (p if home else (pa if pa is not None else 1 - p))
        out.append({"start": str(g.get("date")), "res": _res_letter(us, them), "p": None if pw is None else round(pw, 4), "us": int(us), "them": int(them),
                    "home": home, "opp": str(g.get("away") if home else g.get("home")), "id": str(g.get("id")), "g": g})
    out.sort(key=lambda r: r["start"])
    return out


def upcoming_of(games: list[dict], tid: str, asof: datetime, n: int = 3) -> list[dict]:
    out = []
    for g in games:
        if g.get("status") not in ("pre", None) or g.get("stype") not in COUNTS or tid not in (str(g.get("home")), str(g.get("away"))):
            continue
        t = FL._dt(g.get("date"))
        if t is None or t <= asof:
            continue
        out.append((t, g))
    out.sort(key=lambda x: x[0])
    return [g for _, g in out[:n]]


def _comp(level: str, g: dict, conf_short: str | None) -> str | None:
    st = g.get("stype")
    if st in ("cfp", "ncaa", "bowl", "nit", "cbi", "post"):
        rd = str(g.get("round") or "").strip()
        base = {"cfp": "College Football Playoff", "ncaa": "NCAA tournament", "bowl": "Bowl"}.get(st, "Postseason")
        return f"{base} · {rd.title()}" if rd and st != "bowl" else (g.get("note") or base)
    if st == "conf":
        return f"{conf_short} tournament" if level != "cfb" and conf_short else f"{conf_short or 'Conference'} title game"
    if g.get("conf_game") and conf_short:
        return conf_short
    return None


def _record(level: str, rec: dict) -> str | None:
    w, l_ = rec.get("w"), rec.get("l")
    if _num(w) is None or _num(l_) is None:
        return None
    t = rec.get("t") if level in HOCKEY else None
    return FL.DASH.join([str(int(w)), str(int(l_))] + ([str(int(t))] if _num(t) else []))


def _ranks_by_date(paths: dict, dates: list) -> dict:
    """{date: {tid: rank}} from season.json rating_paths (each team's latest rating at or before the date)."""
    pts = {t: sorted((FL._dt(d), _num(v)) for d, v in (p or []) if FL._dt(d) is not None and _num(v) is not None) for t, p in (paths or {}).items()}
    out = {}
    for d in dates:
        dt = FL._dt(d)
        cur = {}
        for t, ps in pts.items():
            last = None
            for x, v in ps:
                if x > dt:
                    break
                last = v
            if last is not None:
                cur[t] = last
        if len(cur) >= 10:
            out[d] = _rank(cur)
    return out


def build(data: Path, level: str = "cfb", now: datetime | None = None, out_dir: Path | None = None) -> dict:
    """Write data/follow/<level>/<id>.json for every team of the level's current season; returns write_cards' summary."""
    from oddsmarkets.college import canon
    from oddsmarkets.college import site as SITE_MOD
    from oddsmarkets.common import featured as FT
    data = Path(data)
    asof = now or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=timezone.utc)
    idx = _read(data / "index.json") or {}
    li = (idx.get("levels") or {}).get(level) or {}
    season = li.get("current_season")
    if not season:
        raise ValueError(f"no current season for {level} in index.json")
    season = int(season)
    sdir = data / level / str(season)
    sj = _read(sdir / "season.json") or {}
    spec = {m["key"]: m for m in ((_read(sdir / "teams.json") or {}).get("metrics") or []) if m.get("key")}
    tfiles = {}
    for p in sorted((sdir / "teams").glob("*.json")):
        d = _read(p)
        if d and d.get("ok") is not False and (d.get("team") or {}).get("member", True):
            tfiles[str(d.get("id") or p.stem)] = d
    if not tfiles:
        raise ValueError(f"no team files for {level} {season}")
    info = {str(k): dict(v) for k, v in (li.get("teams") or {}).items()}
    for k, v in (sj.get("teams") or {}).items():
        info.setdefault(str(k), dict(v))
    for t, d in tfiles.items():
        info.setdefault(t, dict(d.get("team") or {}))
    confs = sj.get("conferences") or li.get("conferences") or {}
    cshort = lambda c: ((confs.get(str(c)) or {}).get("short") or (confs.get(str(c)) or {}).get("name")) if c is not None else None   # noqa: E731
    sim = ((sj.get("sim") or {}).get("teams") or {}) if isinstance(sj.get("sim"), dict) else {}
    power = [str(r.get("team")) for r in sj.get("power") or [] if r.get("team") is not None]
    if not power:
        power = sorted(tfiles, key=lambda t: -(_num((tfiles[t].get("rating") or {}).get("rating")) or -99))
    rating_rank = {t: i + 1 for i, t in enumerate(power)}
    power_val = {str(r.get("team")): _num(r.get("rating")) for r in sj.get("power") or [] if r.get("team") is not None}
    n_rated = len(rating_rank)
    polls = sj.get("polls") or {}
    poll = polls.get("ap") or polls.get("uscho") or []
    poll_name = "AP" if polls.get("ap") else "USCHO" if polls.get("uscho") else None
    poll_rank = {str(r.get("team")): int(r["rank"]) for r in poll if _num(r.get("rank")) is not None}
    phase = phase_of(li.get("phase") or sj.get("phase"))
    where = LEAGUE_WHERE[level]
    hist = _read(data / level / "history.json") or {}
    champ_row = next((c for c in hist.get("champions") or [] if int(c.get("season") or 0) == season), None)
    if champ_row:
        phase = "offseason"
    final = phase == "offseason"
    # standings: the conference place
    place = {}
    for c, rs in (sj.get("standings") or {}).items():
        rs = sorted(rs, key=lambda r: (_num(r.get("conf_rank")) or 99))
        for i, r in enumerate(rs, 1):
            place[str(r.get("team"))] = (int(r.get("conf_rank") or i), len(rs), c)
    # the chance logs (the race log keeps the season; the chance log the last days, with every team)
    logs: dict = {}
    for name in ("race_log.json", "chance_log.json"):
        lg = (_read(data / level / name) or {}).get(str(season)) or {}
        for key, by_day in lg.items():
            if not isinstance(by_day, dict) or key.startswith("_"):
                continue
            for d, v in by_day.items():
                if isinstance(v, dict):
                    logs.setdefault(key, {}).setdefault(d, {}).update(v)
    # every team's results, records and split ranks
    sched = {t: rows_of(d.get("schedule")) for t, d in tfiles.items()}
    res = {t: results_of(sched[t], t, asof) for t in tfiles}
    rec_of = {t: (tfiles[t].get("record") or {}) for t in tfiles}
    played = {t: int(_num(rec_of[t].get("w")) or 0) + int(_num(rec_of[t].get("l")) or 0) + int(_num(rec_of[t].get("t")) or 0) for t in tfiles}
    min_g = MIN_GAMES[level]

    def wpct(x):
        x = list(x or [])
        n = sum(int(v or 0) for v in x[:3])
        return None if n == 0 else (int(x[0] or 0) + 0.5 * (int(x[2] or 0) if len(x) > 2 else 0)) / n
    side_min = 3 if level == "cfb" else 4
    home_rank = _rank({t: wpct(rec_of[t].get("home")) for t in tfiles if sum(int(v or 0) for v in (rec_of[t].get("home") or [])[:3]) >= side_min})
    away_rank = _rank({t: wpct(rec_of[t].get("away")) for t in tfiles if sum(int(v or 0) for v in (rec_of[t].get("away") or [])[:3]) >= side_min})
    pct_rank = _rank({t: wpct([rec_of[t].get("w"), rec_of[t].get("l"), rec_of[t].get("t")]) for t in tfiles if played[t] >= min_g})
    # league ranks on the team metrics, in the spec's direction
    metric_rank = {}
    for k, m in spec.items():
        if k in NOT_RANKED:
            continue
        vals = {t: _num(((tfiles[t].get("stats") or {}).get(k) or {}).get("v")) for t in tfiles if played[t] >= min_g}
        if len([v for v in vals.values() if v is not None]) >= 10:
            metric_rank[k] = _rank(vals, higher=not m.get("lower"))
    # the schedule left: the remaining opponents' average rating (the season simulation's sos_rem), toughest first
    sos_vals = {t: _num((tfiles[t].get("odds") or {}).get("sos_rem")) for t in tfiles if int(_num((tfiles[t].get("odds") or {}).get("n_rem")) or 0) >= 2}
    sos_rank = _rank(sos_vals) if phase == "season" else {}
    # preseason: the projected offence and defence ranks
    pre_rank = {}
    if phase == "preseason":
        for k in ("off", "def"):
            if k in spec:
                pre_rank[k] = _rank({t: _num(((tfiles[t].get("stats") or {}).get(k) or {}).get("v")) for t in tfiles}, higher=not spec[k].get("lower"))
    # last season's value by position across every roster (a preseason card's star player, before a ball is played)
    roster_pool: dict = {}
    for t0, d0 in tfiles.items():
        if d0.get("roster_basis") == "last_season":
            for p in rows_of(d0.get("roster")):
                if _num(p.get("value")) is not None:
                    roster_pool.setdefault(str(p.get("pos") or "").upper(), []).append(float(p["value"]))
    # our rank a month ago (rating paths)
    a_iso = FL.iso_min(asof)
    month = (asof - timedelta(days=31)).date().isoformat()        # a date-only point is noon: a day's margin keeps it inside "a month ago"
    rbd = _ranks_by_date(sj.get("rating_paths") or {}, [month, a_iso])
    # top players: every team's top performers (value per game; GAR in hockey), else the roster's value
    cards = {}
    for t, d in sorted(tfiles.items()):
        ti = info.get(t) or {}
        rec = rec_of[t]
        short = ti.get("short") or ti.get("name")
        conf = str(ti.get("conference") or (d.get("team") or {}).get("conference") or "")
        cs = cshort(conf) if conf else None
        team = {"name": ti.get("name"), "short": short, "abbr": ti.get("abbr"), "colour": ti.get("colour"), "alt": ti.get("alt") or ti.get("alt_colour"),
                "href": f"#/{level}/team/{t}", "league": LEVEL_LABEL[level], "group": cs if cs and conf != "independent" else ("Independent" if conf == "independent" else None)}
        r_ = res[t]
        record = _record(level, rec) if played[t] or phase != "preseason" else None
        st = None
        pos, of, _c = place.get(t, (None, None, None))
        if pos and played[t] and cs and conf != "independent":
            st = {"pos": pos, "of": of, "group": cs, "text": f"{FL.ordinal(pos)} in the {cs}"}
        R = dict(d.get("rating") or {})
        if power_val.get(t) is not None:
            R["rating"] = power_val[t]                     # the power order's number, so the card and the boards agree
        rt = None
        if _num(R.get("rating")) is not None and t in rating_rank:
            dp = 2 if level in HOCKEY else 1
            rt = {"value": R["rating"], "text": _signed(R["rating"], dp), "rank": rating_rank[t], "of": n_rated,
                  "label": "Preseason rating" if phase == "preseason" else "Rating"}
        now_blk = {"record": record, "form": None if final else FL.form_letters(r_, asof), "standing": st, "rating": rt}
        sk = FL.streak_of(r_, asof)
        if sk and not final and sk[0] in ("W", "L"):
            now_blk["streak"] = f"{sk[0]}{sk[1]}"
        # chances: the field, then the title (the headline is the last: the title once it is a real chance)
        od = d.get("odds") or {}
        s = sim.get(t) or {}
        chances = []
        if not final:
            fk, flab = FIELD[level]
            rows = []
            for key, lab in ((fk, flab), ("p_title", "Title")):
                p = _num(od.get(key)) if _num(od.get(key)) is not None else _num(s.get(key))
                if p is None:
                    continue
                ser = {dd: (v or {}).get(t) for dd, v in (logs.get(key) or {}).items()}
                rows.append({"key": key, "label": lab, "p": round(p, 4), "d7": FL.change_since(ser, asof, 7), "_ser": ser})
            if len(rows) == 2 and rows[1]["p"] < 0.05:
                rows = rows[::-1]                                  # a long shot's headline is the field, not the title
            chances = rows
        # next games
        nxt = []
        for g in (upcoming_of(sched[t], t, asof) if not final else []):
            h, a = str(g.get("home")), str(g.get("away"))
            home = h == t
            o = a if home else h
            oi = info.get(o) or {}
            fg = {"sport": SPORT, "league": SITE_MOD.LEAGUE[level], "id": g.get("id"), "start": g.get("date"), "status": "pre", "home": h, "away": a,
                  "p_home": (g.get("model") or {}).get("p_home"), "sig": SITE_MOD._game_sig(level, g, sim, info)}
            sg = FT.significance(fg, asof)
            M = g.get("model") or {}
            ph, pt = _num(M.get("p_home")), _num(M.get("p_tie"))
            pa = _num(M.get("p_away"))
            p_us = None if ph is None else (ph if home else (pa if pa is not None else 1 - ph - (pt or 0)))
            mk = _num((g.get("market") or {}).get("p_home"))
            nxt.append({"id": str(g.get("id")), "start": g.get("date"), "home": home, "tba": True if canon.time_tba(g) else None,
                        "opp": {"name": oi.get("short") or oi.get("name") or o, "abbr": oi.get("abbr"), "colour": oi.get("colour"), "rank": rating_rank.get(o)},
                        "comp": _comp(level, g, cs), "p": None if p_us is None else round(p_us, 4), "p_draw": pt if level in HOCKEY else None,
                        "mkt": None if mk is None or level in HOCKEY else round(mk if home else 1 - mk, 4),
                        "why": sg["reasons"][:2], "href": f"#/{level}/game/{g.get('id')}",
                        "_score": sg["score"], "_short": oi.get("short") or oi.get("name"), "_reasons": sg["reasons"], "_rivalry": (fg["sig"] or {}).get("rivalry")})
        # the line and the note
        champ = bool(champ_row) and str(champ_row.get("team")) == t
        line = None
        if champ:
            ru = (info.get(str(champ_row.get("runner_up"))) or {}).get("short")
            line = f"Won the {season} national title" + (f", {str(champ_row.get('score') or '').replace('-', FL.DASH)} over {ru}." if ru and champ_row.get("score") else ".")
        elif record and played[t]:
            cw, cl = rec.get("conf_w"), rec.get("conf_l")
            cr = f" ({int(cw)}{FL.DASH}{int(cl)} in the {cs})" if cs and conf != "independent" and _num(cw) is not None and (int(cw) + int(cl or 0)) > 0 else ""
            line = ("Season over: " if final else "") + f"{record}{cr}" + (f", {st['text']}." if st else ".")
        elif phase == "preseason" and rt:
            line = f"Preseason: {FL.ordinal(rt['rank'])} of {n_rated} in our ratings" + (f", {poll_name} No. {poll_rank[t]}." if t in poll_rank else ".")
        note = None
        if not nxt:
            note = (f"Off-season. The {season + 1 if level == 'cfb' else season} schedule is not out yet." if final else
                    "Season over." if phase == "postseason" else "No games on the schedule in the next few weeks.")
        last = None
        if r_:
            x = r_[-1]
            oi = info.get(x["opp"]) or {}
            last = {"id": x["id"], "start": x["start"], "home": x["home"], "opp": {"name": oi.get("short") or oi.get("name") or x["opp"], "abbr": oi.get("abbr"), "colour": oi.get("colour")},
                    "score": [x["us"], x["them"]], "res": x["res"], "p": x["p"], "upset": FL.upset_flag(x["p"], x["res"]),
                    "comp": _comp(level, x["g"], cs), "href": f"#/{level}/game/{x['id']}"}
        # the profile: the team page's strengths and needs (units graded A to F, league percentiles)
        def unit_row(u):
            return {"id": u.get("key") or u.get("unit"), "label": uk(u.get("unit")).split(" (")[0], "pct": int(round(float(u["pctl"]))), "text": u.get("grade") or ""}
        strong = [unit_row(u) for u in d.get("strengths") or [] if _num(u.get("pctl")) is not None]
        weak = [unit_row(u) for u in d.get("needs") or [] if _num(u.get("pctl")) is not None]
        weak = [w for w in weak if w["id"] not in {x["id"] for x in strong}]
        strong = [x for x in strong if x["pct"] >= 50]
        weak = [x for x in weak if x["pct"] < 50]
        profile = {"strong": strong[:3], "weak": sorted(weak, key=lambda x: x["pct"])[:2]} if strong or weak else None
        # top players: top performers (this season), else the roster's value (last season's, before a ball is played)
        tp = d.get("top_performers") or {}
        players, top_ctx = [], None
        plural = POS_PLURAL[level]
        over = [p for p in tp.get("overall") or [] if _num(p.get("v")) is not None]
        if over:
            lab = "GAR" if tp.get("key") == "gar" else "value a game" if tp.get("key") == "value_pg" else (tp.get("label") or "value")
            dp = 2 if tp.get("key") == "gar" else 1
            players = [{"name": p.get("name"), "pos": p.get("pos"), "metric": "GAR" if tp.get("key") == "gar" else (tp.get("label") or "Value"), "value": p["v"],
                        "text": f"{float(p['v']):.{dp}f}", "href": f"#/{level}/player/{p.get('id')}"} for p in over[:2]]
            p0 = over[0]
            if _num(p0.get("rank")) is not None and _num(p0.get("n")) is not None:
                top_ctx = {"name": p0.get("name"), "text": f"{float(p0['v']):.{dp}f}", "metric": lab, "rank": int(p0["rank"]), "of": int(p0["n"]),
                           "pool": f"{tp.get('pool') or POOL[level]} {plural.get(str(p0.get('pos') or '').upper(), 'players')}"}
        else:
            ro = sorted((p for p in rows_of(d.get("roster")) if _num(p.get("value")) is not None), key=lambda p: -float(p["value"]))
            basis = d.get("roster_basis")
            players = [{"name": p.get("name"), "pos": p.get("pos"), "metric": "Value, last season" if basis == "last_season" else "Value", "value": round(float(p["value"]), 1),
                        "text": f"{float(p['value']):.1f}", "href": f"#/{level}/player/{p.get('id')}"} for p in ro[:2]]
            if ro and basis == "last_season":
                p0 = ro[0]
                pool_v = roster_pool.get(str(p0.get("pos") or "").upper()) or []
                if pool_v:
                    top_ctx = {"name": p0.get("name"), "text": f"{float(p0['value']):.1f}", "metric": "value last season",
                               "rank": 1 + sum(1 for v in pool_v if v > float(p0["value"])), "of": len(pool_v),
                               "tied": sum(1 for v in pool_v if v == float(p0["value"])) > 1,
                               "pool": f"{POOL[level]} {plural.get(str(p0.get('pos') or '').upper(), 'players')}"}
        # ── the facts
        ctx = {"name": ti.get("name"), "short": short, "the": False, "phase": phase, "final": final, "league_name": where, "results": r_}
        if phase == "preseason":
            # before a game: the projected offence and defence (our preseason ratings) against the level
            pr = []
            for k in ("off", "def"):
                rk = pre_rank.get(k) or {}
                if t in rk and k in spec:
                    pr.append({"label": "preseason " + uk(spec[k].get("label") or k).lower(), "rank": rk[t], "of": len(rk), "tied": _tie_size(rk, t) > 1,
                               "text": _fmt(((d.get("stats") or {}).get(k) or {}).get("v"), spec[k].get("fmt")), "model": True})
            ctx["pctl"] = pr
        if played[t] >= min_g:
            pr = []
            for k, rk in metric_rank.items():
                if t in rk and _tie_size(rk, t) <= 2:
                    m = spec[k]
                    pr.append({"label": uk(m.get("label") or k), "rank": rk[t], "of": len(rk), "tied": _tie_size(rk, t) > 1,
                               "text": _fmt(((d.get("stats") or {}).get(k) or {}).get("v"), m.get("fmt")), "model": m.get("group") in ("Model", "Our ratings")})
            ctx["pctl"] = pr
            if pct_rank.get(t) in (1, 2) and _tie_size(pct_rank, t) == 1 and record:
                ctx["best_record"] = {"record": record, "scope": "league", "where": where, "rank": pct_rank[t]}
            elif pos == 1 and cs and conf != "independent" and int(_num(rec.get("conf_w")) or 0) + int(_num(rec.get("conf_l")) or 0) >= 2 and record:
                ctx["best_record"] = {"record": record, "scope": "group", "where": cs}
        sp = {"of": len(home_rank), "league": where}
        for side, rk in (("home", home_rank), ("away", away_rank)):
            x = rec.get(side) or []
            if t in rk and _tie_size(rk, t) <= 2:
                sp[side] = {"record": FL.DASH.join(str(int(v or 0)) for v in (x[:3] if level in HOCKEY and len(x) > 2 and x[2] else x[:2])), "rank": rk[t], "tied": _tie_size(rk, t) > 1}
        ctx["split"] = sp
        if t in sos_rank:
            ctx["sos"] = {"rank": sos_rank[t], "of": len(sos_rank), "left": int(_num(od.get("n_rem")) or 0), "where": where,
                          "text": _signed(od.get("sos_rem"), 2 if level in HOCKEY else 1)}
        if month in rbd and a_iso in rbd and t in rbd[month] and t in rbd[a_iso]:
            ctx["rating_ranks"] = [[month, rbd[month][t]], [a_iso, rbd[a_iso][t]]]
        ctx["chances"] = [{"label": "playoff" if c["key"] == "p_cfp" else "tournament" if c["key"] == "p_ncaa" else "title", "series": c.pop("_ser")} for c in chances]
        if nxt:
            g0 = nxt[0]
            ctx["next"] = {"start": g0["start"], "opp": {"short": g0["_short"], "name": g0["opp"]["name"]}, "p": g0["p"], "score": g0["_score"],
                           "reasons": g0["_reasons"], "rivalry": g0["_rivalry"]}
        if top_ctx:
            ctx["players"] = [top_ctx]
        if champ:
            ctx["champion"] = {"event": "national", "season": season}
        if rt:
            ctx["rating"] = {"rank": rt["rank"], "of": rt["of"], "text": rt["text"]}
        fx = FL.facts(ctx, asof)
        if any(f["kind"] == "rating_move" for f in fx):
            fx = [f for f in fx if f["kind"] != "rating"]  # one line on our ratings is enough
        for g in nxt:
            for k in ("_score", "_short", "_reasons", "_rivalry"):
                g.pop(k, None)
        champion = {"event": "national", "season": season, "text": line} if champ else None
        cards[t] = FL.make_card(site=SITE, sport=SPORT, scope=level, ident=t, team=team, asof=asof, phase=phase, season=season,
                                now=now_blk, chances=chances, next_games=nxt, next_note=note, last=last, line=line, profile=profile,
                                facts=fx, players=players, champion=champion)
    return FL.write_cards(out_dir or (data / "follow"), level, cards)


def main(argv=None) -> int:
    import argparse
    from oddsmarkets.college import store
    ap = argparse.ArgumentParser(description="Write the Campus's follow cards from the payloads on disk")
    ap.add_argument("--data", default=None)
    ap.add_argument("--levels", nargs="*", default=list(LEVELS))
    ap.add_argument("--now", default=None, help="ISO build clock (default now)")
    a = ap.parse_args(argv)
    data = Path(a.data) if a.data else Path(store.paths()["data"])
    now = FL._dt(a.now) if a.now else None
    for lv in a.levels:
        s = build(data, lv, now)
        print(f"{lv}: {s['n']} cards, {s['bytes'] / 1024:.0f} KB, largest {s['max']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
