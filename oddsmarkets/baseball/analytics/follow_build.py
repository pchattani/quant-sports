"""The Bullpen's follow cards (My Teams): one small card per club at data/follow/<L>/<tid>.json, for MLB and Triple-A.

The schema and the fact engine are oddsmarkets/common/follow.py; this module only gathers what the Bullpen build has
already written this run (no new fetching):

    index.json                    the clubs (names, colours), the phase, the champion (digest.stage.title), Triple-A's
                                  club names (levels.aaa.teams)
    <L>/<S>/season.json           standings (record, streak, place, games behind), ratings, the league block (profile
                                  percentiles, luck, the race: magic numbers, the schedule left, the clinches)
    <L>/<S>/schedule.json         every game: results with the frozen pre-game chance, and the games still to come
    <L>/<S>/teams.json            rosters (the top two players by Bullpen WAR)
    <L>/<S-1>/season.json         last season's records, and <L>/<S-1>/schedule.json for "at this point last season"
    <L>/<S+1>/schedule.json       next season's Opening Day, when the schedule is out
    mlb/race_log.json             our postseason and World Series chances by day (the 7-day change)
    mlb/team_history.json         franchise titles and best seasons (a first title, a wins record)
    <L>/<S>/form.json             hitters and pitchers on a run

    build(data_root, level, now=None) -> {"n", "bytes", "max", "ids"}        (python -m oddsmarkets.baseball.analytics.follow_build)

No look-ahead: a result counts only once its start is at or before the build clock, a finished game's chance is the
schedule's model price frozen before the first pitch, and the 7-day change compares two race-log snapshots taken on
those days.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL

log = logging.getLogger(__name__)

SITE, SPORT = "bullpen", "baseball"
PHASE = {"preseason": "preseason", "regular": "season", "postseason": "postseason", "offseason": "offseason", "complete": "offseason"}
GAME_TYPES = ("R", "F", "D", "L", "W", "C")          # regular season and the postseason rounds (no spring games)
ROUND_NAME = {"F": "Wild Card Series", "D": "Division Series", "L": "Championship Series", "W": "World Series", "C": "Championship Series"}
LEVEL_NAME = {"mlb": "MLB", "aaa": "Triple-A"}


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _num(x):
    return FL._num(x)


def _fmt(v, f: str | None) -> str:
    v = _num(v)
    if v is None:
        return ""
    if f == "+2":
        return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v):.2f}"
    if f == "+1":
        return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v):.1f}"
    m = "−" if v < 0 else ""
    a = abs(v)
    if f == "3":
        return m + (f"{a:.3f}".replace("0.", ".", 1) if a < 1 else f"{a:.3f}")
    if f == "pct1":
        return m + f"{a * 100:.1f}%"
    if f == "1":
        return m + f"{a:.1f}"
    if f == "0":
        return m + f"{a:.0f}"
    return m + f"{a:g}"


def _signed2(v) -> str:
    return _fmt(v, "+2")


def _when(g: dict) -> datetime | None:
    return FL._dt(g.get("start") or g.get("date"))


def _side_p(g: dict, tid: str, key: str = "model") -> float | None:
    p = _num((g.get(key) or {}).get("p_home"))
    if p is None:
        return None
    return round(p if str(g.get("home")) == tid else 1 - p, 4)


def results_of(games: list[dict], tid: str, asof: datetime) -> list[dict]:
    """The club's finished games at `asof`, oldest first, as follow.py results: {"start", "res", "p", "us", "them",
    "home", "opp", "gpk", "gtype", "series"}. Spring and exhibition games are left out."""
    out = []
    for g in games:
        if g.get("gtype") not in GAME_TYPES or g.get("status") != "final" or tid not in (str(g.get("home")), str(g.get("away"))):
            continue
        t = _when(g)
        hs, as_ = _num(g.get("hs")), _num(g.get("as"))
        if t is None or t > asof or hs is None or as_ is None:
            continue
        home = str(g.get("home")) == tid
        us, them = (hs, as_) if home else (as_, hs)
        out.append({"start": str(g.get("start") or g.get("date")), "res": "W" if us > them else "L", "p": _side_p(g, tid), "us": int(us), "them": int(them),
                    "home": home, "opp": str(g.get("away") if home else g.get("home")), "gpk": str(g.get("gpk")),
                    "gtype": g.get("gtype"), "series": g.get("series")})
    out.sort(key=lambda r: r["start"])
    return out


def upcoming_of(games: list[dict], tid: str, asof: datetime, n: int = 3) -> list[dict]:
    """The club's next n games that have not started at `asof` (cancelled and postponed games left out)."""
    out = []
    for g in games:
        if g.get("gtype") not in GAME_TYPES or g.get("status") in ("final", "cancelled", "postponed", "live"):
            continue
        if tid not in (str(g.get("home")), str(g.get("away"))):
            continue
        t = _when(g)
        if t is None or t <= asof:
            continue
        out.append((t, g))
    out.sort(key=lambda x: x[0])
    return [g for _, g in out[:n]]


def _record_at(games: list[dict], tid: str, n: int) -> tuple[int, int] | None:
    """The club's regular-season record after its first n games of a season (None when it played fewer)."""
    rs = []
    for g in sorted((g for g in games if g.get("gtype") == "R" and g.get("status") == "final"), key=lambda g: str(g.get("start") or g.get("date"))):
        if tid not in (str(g.get("home")), str(g.get("away"))):
            continue
        hs, as_ = _num(g.get("hs")), _num(g.get("as"))
        if hs is None or as_ is None:
            continue
        home = str(g.get("home")) == tid
        rs.append((hs > as_) if home else (as_ > hs))
    if len(rs) < n or n <= 0:
        return None
    w = sum(1 for x in rs[:n] if x)
    return w, n - w


def _ties(rank: dict) -> set:
    """The keys that share their rank with another."""
    seen: dict = {}
    for k, r in rank.items():
        seen.setdefault(r, []).append(k)
    return {k for ks in seen.values() if len(ks) > 1 for k in ks}


def _rank(values: dict, higher: bool = True) -> dict:
    """{key: rank} with 1 the best (ties share the better rank)."""
    xs = sorted(((v, k) for k, v in values.items() if _num(v) is not None), key=lambda t: -t[0] if higher else t[0])
    out, prev, prev_rank = {}, None, 0
    for i, (v, k) in enumerate(xs, 1):
        r = prev_rank if prev is not None and v == prev else i
        out[k] = r
        prev, prev_rank = v, r
    return out


def opening_day(data: Path, level: str, season: int) -> str | None:
    """The first regular-season date of `season`, when its schedule is out (data/<L>/<season>/schedule.json)."""
    sch = _read(data / level / str(season) / "schedule.json") or {}
    days = sorted(str(g.get("date"))[:10] for g in sch.get("games") or [] if g.get("gtype") == "R" and g.get("date"))
    return days[0] if days else None


def _nice_day(s: str) -> str:
    d = date.fromisoformat(s[:10])
    return f"{('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[d.weekday()]} {d.day} {('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[d.month - 1]} {d.year}"


def build(data: Path, level: str = "mlb", now: datetime | None = None, out_dir: Path | None = None) -> dict:
    """Write data/follow/<level>/<tid>.json for every club of the level's current season; returns write_cards' summary."""
    data = Path(data)
    asof = now or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=timezone.utc)
    idx = _read(data / "index.json") or {}
    lv = (idx.get("levels") or {}).get(level) or {}
    season = lv.get("season") or (idx.get("season") if level == "mlb" else None)
    if not season:
        raise ValueError(f"no current season for {level} in index.json")
    sdir = data / level / str(season)
    sj = _read(sdir / "season.json") or {}
    sch = (_read(sdir / "schedule.json") or {}).get("games") or []
    tms = (_read(sdir / "teams.json") or {}).get("teams") or {}
    prev_s = _read(data / level / str(season - 1) / "season.json") or {}
    prev_sch = None                                                # read only when needed (1 MB)
    raw_phase = str(lv.get("phase") or sj.get("phase") or (idx.get("phase") if level == "mlb" else "") or "regular")
    phase = PHASE.get(raw_phase, "season")
    final = phase == "offseason" or (phase == "postseason")
    lgname = LEVEL_NAME.get(level, level.upper())
    info = dict((idx.get("teams") or {}) if level == "mlb" else (lv.get("teams") or {}))
    # standings rows by club, with the place in the group
    rows, place = {}, {}
    for grp, rs in (sj.get("standings") or {}).items():
        rs = sorted(rs, key=lambda r: (_num(r.get("gb")) if _num(r.get("gb")) is not None else 99, -(_num(r.get("pct")) or 0)))
        for i, r in enumerate(rs, 1):
            t = str(r.get("tid"))
            rows[t] = r
            place[t] = (i, len(rs), grp)
            info.setdefault(t, {k: r.get(k) for k in ("name", "abbr", "short", "league", "division")})
    for t, x in tms.items():
        info.setdefault(str(t), {k: x.get(k) for k in ("name", "abbr", "short", "league", "division", "colour", "alt")})
        for k in ("colour", "alt"):
            if not info[str(t)].get(k) and x.get(k):
                info[str(t)][k] = x[k]
    teams = sorted(t for t in info if t in rows or t in tms)
    if not teams:
        raise ValueError(f"no clubs for {level} {season}")
    ratings = {t: _num((sj.get("ratings") or {}).get(t, {}).get("total")) if isinstance((sj.get("ratings") or {}).get(t), dict)
               else _num(rows.get(t, {}).get("rating")) for t in teams}
    rating_rank = _rank(ratings)
    pct_rank = _rank({t: _num(rows.get(t, {}).get("pct")) for t in teams})
    L = sj.get("league") or {}
    prof_spec = (L.get("profile") or {}).get("metrics") or []
    lteams = L.get("teams") or {}
    race = L.get("race") or {}
    # the 7-day change: the race log (mlb only)
    rlog = ((_read(data / "mlb" / "race_log.json") or {}).get(str(season)) or {}) if level == "mlb" else {}
    th = (_read(data / "mlb" / "team_history.json") or {}) if level == "mlb" else {}
    fr_by_tid = {str(v.get("tid")): v for v in (th.get("franchises") or {}).values() if isinstance(v, dict)}
    stage = ((idx.get("digest") or {}).get("stage") or {}) if level == "mlb" else {}
    title = stage.get("title") if isinstance(stage.get("title"), dict) else None
    post = (idx.get("postseason") or {}) if level == "mlb" else {}
    form = _read(sdir / "form.json") or {}
    # every club's results and the league-wide home and road records
    res = {t: results_of(sch, t, asof) for t in teams}
    split_w = {}
    for t in teams:
        reg = [r for r in res[t] if r["gtype"] == "R"]
        hw = sum(1 for r in reg if r["home"] and r["res"] == "W"); hl = sum(1 for r in reg if r["home"] and r["res"] == "L")
        aw = sum(1 for r in reg if not r["home"] and r["res"] == "W"); al = sum(1 for r in reg if not r["home"] and r["res"] == "L")
        split_w[t] = {"home": (hw, hl), "away": (aw, al)}
    home_rank = _rank({t: (v["home"][0] / max(1, sum(v["home"]))) for t, v in split_w.items() if sum(v["home"]) >= 10})
    away_rank = _rank({t: (v["away"][0] / max(1, sum(v["away"]))) for t, v in split_w.items() if sum(v["away"]) >= 10})
    # the players: Bullpen WAR across every roster, hitters and pitchers apart
    pool = {"hitter": [], "pitcher": []}
    for t, x in tms.items():
        for p in x.get("roster") or []:
            if _num(p.get("war")) is not None and p.get("kind") in pool:
                pool[p["kind"]].append(float(p["war"]))
    for k in pool:
        pool[k].sort(reverse=True)
    od = opening_day(data, level, season + 1) if phase in ("offseason", "postseason") else None
    cards = {}
    for t in teams:
        tinfo = info.get(t) or {}
        r = rows.get(t) or {}
        pos, of, grp = place.get(t, (None, None, tinfo.get("division")))
        short = tinfo.get("short") or tinfo.get("name")
        team = {"name": tinfo.get("name"), "short": short, "abbr": tinfo.get("abbr"), "colour": tinfo.get("colour"),
                "alt": tinfo.get("alt"), "href": f"#/{level}/team/{t}", "league": lgname,
                "group": grp}
        w, l = r.get("w"), r.get("l")
        rec = FL.record_text(w, l)
        st = None
        if pos:
            gb = _num(r.get("gb"))
            st = {"pos": pos, "of": of, "group": grp, "gb": gb if gb else None,
                  "text": f"{FL.ordinal(pos)} in the {grp}" + (f", {gb:g} back" if gb and gb > 0 else "")}
        rt = None
        if ratings.get(t) is not None:
            rt = {"value": ratings[t], "text": _signed2(ratings[t]), "rank": rating_rank.get(t), "of": len([v for v in ratings.values() if v is not None]),
                  "label": "Team rating"}
        # the off-season card shows how the season ended, never last October's form as if it were current
        now_blk = {"record": rec, "form": None if phase == "offseason" else FL.form_letters(res[t], asof), "streak": None, "standing": st, "rating": rt}
        sk = FL.streak_of(res[t], asof)
        if sk and phase != "offseason":
            now_blk["streak"] = f"{sk[0]}{sk[1]}"
        # chances (the simulation; none in the off-season, when every race is settled)
        chances = []
        if level == "mlb" and phase != "offseason":
            pt = (post.get("teams") or {}).get(t) or {}
            for key, lab in (("p_postseason", "Postseason"), ("p_ws", "World Series")):
                if phase == "postseason" and key == "p_postseason":
                    continue
                p = _num(pt.get(key)) if _num(pt.get(key)) is not None else _num(r.get(key))
                if p is None:
                    continue
                ser = {d: (v or {}).get(t) for d, v in (rlog.get(key) or {}).items() if isinstance(v, dict)}
                chances.append({"key": key, "label": lab, "p": round(p, 4), "d7": FL.change_since(ser, asof, 7)})
        # next games
        nxt = []
        from oddsmarkets.common import featured as FT
        for g in (upcoming_of(sch, t, asof) if phase != "offseason" else []):
            home = str(g.get("home")) == t
            o = str(g.get("away") if home else g.get("home"))
            oi = info.get(o) or {}
            sig = {"playoff": [_num(rows.get(str(g.get("home")), {}).get("p_postseason")), _num(rows.get(str(g.get("away")), {}).get("p_postseason"))]}
            fg = {"sport": SPORT, "league": lgname, "id": g.get("gpk"), "start": g.get("start"), "status": "pre",
                  "p_home": (g.get("model") or {}).get("p_home"), "sig": sig}
            if g.get("series"):
                fg["sig"]["series"] = {"game": (g["series"] or {}).get("game"), "best_of": (g["series"] or {}).get("of"), "name": (g["series"] or {}).get("desc")}
                fg["sig"]["stage"] = {"W": "final", "L": "semi", "C": "semi", "D": "quarter", "F": "playoff"}.get(g.get("gtype"), "playoff")
            sg = FT.significance(fg, asof)
            nxt.append({"id": str(g.get("gpk")), "start": g.get("start") or g.get("date"), "home": home,
                        "opp": {"name": oi.get("short") or oi.get("name") or o, "abbr": oi.get("abbr"), "colour": oi.get("colour"), "rank": rating_rank.get(o)},
                        "comp": ((g.get("series") or {}).get("desc")) or (lgname if g.get("gtype") == "R" else ROUND_NAME.get(g.get("gtype"), lgname)),
                        "p": _side_p(g, t), "mkt": _side_p(g, t, "market"), "why": sg["reasons"][:2], "href": f"#/{level}/game/{g.get('gpk')}",
                        "_score": sg["score"], "_short": oi.get("short"), "_reasons": sg["reasons"]})
        # the season line and the note under an empty fixture list
        champ = title if title and str(title.get("champion")) == t else None
        out_in = None
        for s in (post.get("series") or []):
            tm = [str(x) for x in s.get("teams") or []]
            if t in tm and s.get("done") and str(s.get("winner")) != t:
                wins = s.get("wins") or [0, 0]
                i = tm.index(t)
                opp = tm[1 - i]
                out_in = {"round": s.get("round_name") or s.get("round"), "us": wins[i], "them": wins[1 - i], "opp": (info.get(opp) or {}).get("short") or opp}
        line = None
        if champ:
            ro = (info.get(str(champ.get("runner_up"))) or {}).get("short") or str(champ.get("runner_up"))
            rr = champ.get("result") or [None, None]
            line = f"Won the {season} {champ.get('event') or 'World Series'}, {rr[0]}{FL.DASH}{rr[1]} over the {ro}."
        elif out_in:
            line = f"{'Season over: ' if phase == 'offseason' else ''}out in the {out_in['round']}, {out_in['us']}{FL.DASH}{out_in['them']} to the {out_in['opp']}."
        elif final and rec:
            missed = level == "mlb" and _num(r.get("p_postseason")) == 0
            line = f"Season over: {rec}{', ' + st['text'] if st else ''}." + (" Missed the postseason." if missed else "")
        elif rec:
            line = f"{rec}{', ' + st['text'] if st else ''}."
        note = None
        if not nxt:
            if phase in ("offseason", "postseason") and (champ or out_in or final):
                note = (f"Off-season. Opening Day {season + 1}: {_nice_day(od)}." if od else
                        f"Off-season. The {season + 1} schedule is not out yet.")
            elif phase == "preseason":
                note = f"Opening Day: {_nice_day(opening_day(data, level, season))}." if opening_day(data, level, season) else "The schedule is not out yet."
            else:
                note = "No games in the next few days."
        last = None
        if res[t]:
            x = res[t][-1]
            oi = info.get(x["opp"]) or {}
            last = {"id": x["gpk"], "start": x["start"], "home": x["home"], "opp": {"name": oi.get("short") or oi.get("name") or x["opp"], "abbr": oi.get("abbr"), "colour": oi.get("colour")},
                    "score": [x["us"], x["them"]], "res": x["res"], "p": x["p"], "upset": FL.upset_flag(x["p"], x["res"]),
                    "comp": ((x.get("series") or {}).get("desc")) or (lgname if x["gtype"] == "R" else ROUND_NAME.get(x["gtype"], lgname)),
                    "href": f"#/{level}/game/{x['gpk']}"}
        # the profile: the league block's percentiles on the team spec
        lt = lteams.get(t) or {}
        pc, vals = lt.get("pct") or {}, lt.get("vals") or {}
        prof_rows = [{"id": m["id"], "label": m.get("label") or m["id"], "pct": int(round(pc[m["id"]])), "text": _fmt(vals.get(m["id"]), m.get("fmt"))}
                     for m in prof_spec if _num(pc.get(m.get("id"))) is not None and not m.get("style")]
        prof_rows.sort(key=lambda x: -x["pct"])
        profile = {"strong": prof_rows[:3], "weak": sorted(prof_rows[3:], key=lambda x: x["pct"])[:2]} if len(prof_rows) >= 5 else None
        # top players
        roster = sorted((p for p in ((tms.get(t) or {}).get("roster") or []) if _num(p.get("war")) is not None), key=lambda p: -float(p["war"]))
        players = [{"name": p.get("name"), "pos": p.get("pos"), "metric": "WAR", "value": round(float(p["war"]), 1), "text": f"{float(p['war']):.1f}",
                    "href": f"#/{level}/{'pitcher' if p.get('kind') == 'pitcher' else 'hitter'}/{p.get('pid')}"} for p in roster[:2]]
        # ── the facts
        ctx = {"name": tinfo.get("name"), "short": short, "the": True, "phase": phase, "final": final, "league_name": lgname,
               "results": res[t]}
        if level == "mlb" and prof_spec:
            pr = []
            for m in prof_spec:
                if m.get("id") == "rating":
                    continue                                      # the rating has its own fact (follow.py _f_rating)
                vals_all = {x: _num(((lteams.get(x) or {}).get("vals") or {}).get(m["id"])) for x in teams}
                rk = _rank(vals_all, higher=m.get("dir", "higher") != "lower")
                if t in rk:
                    pr.append({"label": m.get("label") or m["id"], "rank": rk[t], "of": len(rk), "tied": t in _ties(rk),
                               "text": _fmt(vals.get(m["id"]), m.get("fmt")), "model": bool(m.get("model"))})
            ctx["pctl"] = pr
        if pct_rank.get(t) in (1, 2) and rec:
            ctx["best_record"] = {"record": rec, "scope": "league", "where": lgname, "rank": pct_rank[t]}
        elif pos == 1 and rec and grp:
            ctx["best_record"] = {"record": rec, "scope": "group", "where": grp}
        sp = split_w.get(t) or {}
        ctx["split"] = {"of": len(home_rank), "league": lgname,
                        "home": {"record": FL.record_text(*sp.get("home", (None, None))), "rank": home_rank.get(t)},
                        "away": {"record": FL.record_text(*sp.get("away", (None, None))), "rank": away_rank.get(t)}}
        luck = lt.get("luck") or {}
        if _num(luck.get("d")) is not None and _num(luck.get("a")) is not None:
            ctx["luck"] = {"d": luck["d"], "unit": "wins", "basis": "BaseRuns says their hits, walks and outs deserved"}
        rc = race.get(t) or {}
        if rc.get("sos") and phase == "season":
            avg, rk, left = rc["sos"]
            ctx["sos"] = {"rank": rk, "of": len(teams), "left": left, "where": lgname, "text": _signed2(avg)}
        if rc.get("magic") and phase == "season":
            ctx["clinch"] = {"magic": rc["magic"], "what": f"the {grp}" if grp else "the division"}
        ctx["chances"] = [{"label": c["label"], "series": {d: (v or {}).get(t) for d, v in (rlog.get(c["key"]) or {}).items() if isinstance(v, dict)}}
                          for c in chances]
        if nxt:
            g0 = nxt[0]
            ctx["next"] = {"start": g0["start"], "opp": {"short": g0["_short"], "name": g0["opp"]["name"]}, "p": g0["p"], "score": g0["_score"],
                           "reasons": g0["_reasons"], "rivalry": FL.rivalry(short, g0["_short"])}
        if roster:
            p0 = roster[0]
            kind = "pitcher" if p0.get("kind") == "pitcher" else "hitter"
            pl = pool.get(kind) or []
            rk = 1 + sum(1 for v in pl if v > float(p0["war"]))
            tied = sum(1 for v in pl if v == float(p0["war"])) > 1
            ctx["players"] = [{"name": p0.get("name"), "text": f"{float(p0['war']):.1f}", "metric": "Bullpen WAR", "rank": rk, "of": len(pl), "tied": tied,
                               "pool": f"{lgname} {kind}s"}]
        runs = []
        for kind, word, unit in (("hitters", "xwOBA+", "plate appearances"), ("pitchers", "Pitching+", "pitches")):
            for p in ((form.get(kind) or {}).get("hot") or []):
                if str(p.get("team")) == t and _num(p.get("recent")) is not None and _num(p.get("season")) is not None:
                    fmt = (lambda v: f"{v:.3f}".lstrip("0")) if kind == "hitters" else (lambda v: f"{v:.0f}")
                    span = "100 plate appearances" if kind == "hitters" else "500 pitches"
                    runs.append({"asof": form.get("asof"), "text": f"{p['name']} is on a run: {word} {fmt(p['recent'])} over his last {span}, against {fmt(p['season'])} for the season."})
        ctx["player_runs"] = runs[:1]
        if prev_s.get("standings"):
            prow = next((x for g in prev_s["standings"].values() for x in g if str(x.get("tid")) == t), None)
            if prow and _num(prow.get("w")) is not None and _num(w) is not None:
                if final or phase == "offseason":
                    ctx["vs_last"] = {"now": [int(w), int(l)], "last": [int(prow["w"]), int(prow["l"])], "season_last": season - 1, "full": True}
                elif (int(w) + int(l)) >= 20:
                    if prev_sch is None:
                        prev_sch = (_read(data / level / str(season - 1) / "schedule.json") or {}).get("games") or []
                    at = _record_at(prev_sch, t, int(w) + int(l))
                    if at:
                        ctx["vs_last"] = {"now": [int(w), int(l)], "last": list(at), "season_last": season - 1}
        fr = fr_by_tid.get(t)
        if champ:
            c = {"event": champ.get("event") or "World Series", "season": season, "result": champ.get("result"),
                 "opp": (info.get(str(champ.get("runner_up"))) or {}).get("short"), "pre_p": champ.get("pre_p"),
                 "pre_rank": champ.get("pre_rank"), "pre_n": champ.get("pre_n")}
            if fr:
                before = int(fr.get("titles") or 0) - (1 if int(fr.get("last") or 0) >= season and fr.get("last_title") == season else 0)
                if before == 0:
                    c["first_title"] = True
                    if fr.get("first"):
                        c["seasons"] = season - int(fr["first"]) + 1
                elif fr.get("last_title") and int(fr["last_title"]) < season:
                    c["since"] = fr["last_title"]
            ctx["champion"] = c
        fb = (fr or {}).get("best") or {}
        if fr and final and int(fr.get("last") or 0) < season and _num(fb.get("pct")) is not None and _num(r.get("pct")) is not None:
            ctx["franchise"] = {"pct": r["pct"], "record": rec, "best_pct": fb["pct"], "best_record": FL.record_text(fb.get("w"), fb.get("l")),
                                "best_season": fb.get("season"), "final": True}
        if rt:
            ctx["rating"] = {"rank": rt["rank"], "of": rt["of"], "text": rt["text"], "unit": "runs a game"}
        fx = FL.facts(ctx, asof)
        for g in nxt:
            for k in ("_score", "_short", "_reasons"):
                g.pop(k, None)
        champion = {"event": champ.get("event") or "World Series", "season": season, "text": line} if champ else None
        cards[t] = FL.make_card(site=SITE, sport=SPORT, scope=level, ident=t, team=team, asof=asof, phase=phase, season=season,
                                now=now_blk, chances=chances, next_games=nxt, next_note=note, last=last, line=line, profile=profile,
                                facts=fx, players=players, champion=champion)
    return FL.write_cards(out_dir or (data / "follow"), level, cards)


def main(argv=None) -> int:
    import argparse
    from oddsmarkets.baseball import analytics as an
    ap = argparse.ArgumentParser(description="Write the Bullpen's follow cards from the payloads on disk")
    ap.add_argument("--data", default=None)
    ap.add_argument("--levels", nargs="*", default=["mlb", "aaa"])
    ap.add_argument("--now", default=None, help="ISO build clock (default now)")
    a = ap.parse_args(argv)
    data = Path(a.data) if a.data else an.data_root()
    now = FL._dt(a.now) if a.now else None
    for lv in a.levels:
        s = build(data, lv, now)
        print(f"{lv}: {s['n']} cards, {s['bytes'] / 1024:.0f} KB, largest {s['max']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
