"""The Hardwood's follow cards (My Teams): one small card per team at data/follow/<L>/<tid>.json, for the NBA and WNBA.

The schema and the fact engine are oddsmarkets/common/follow.py; this module only gathers what the Hardwood build has
already written (no new fetching):

    index.json                    each league's current season, phase, teams (names, colours, conferences), the
                                  freshest today / next / last games, and the champions list
    <L>/<S>/season.json           standings (record, seed, games behind, home and road), the season simulation
                                  (playoff and title chances, magic numbers), ratings and the power order, rating
                                  paths, the postseason series, and the league block (profile percentiles, luck,
                                  the schedule left)
    <L>/<S>/schedule.json         every game: results with the chance frozen before the game, and the games to come
    <L>/<S>/teams.json            rosters with HPM and minutes (the top two players when value.json has no rows)
    <L>/<S>/value.json            wins above replacement (the top two players, and their rank in the league)
    <L>/<S-1>/teams.json          last season's game logs ("at this point last season") and records
    <L>/race_log.json             our playoff and title chances by day (the 7-day change; the pre-playoff title call)
    <L>/history.json              champions, for a first title or the first since a year

    build(data_root, league, now=None) -> {"n", "bytes", "max", "ids"}    (python -m oddsmarkets.basketball.analytics.follow_build)

Phases: preseason and the regular season read as the season; the play-in and the playoffs as the postseason; a
decided Finals, or the off-season, as the off-season (form and chances left out; the card leads with the champion or
how the season ended).

No look-ahead: a result counts only once its start is at or before the build clock, a finished game's chance is the
schedule's chance from the ratings before its day, the 7-day change compares two race-log snapshots taken on those
days, and the title call is the last race-log snapshot before the first playoff game.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL

log = logging.getLogger(__name__)

SITE, SPORT = "hardwood", "basketball"
LEAGUE_NAME = {"nba": "NBA", "wnba": "WNBA"}
PHASE = {"preseason": "preseason", "regular": "season", "playin": "postseason", "playoffs": "postseason", "offseason": "offseason"}
COUNTS = ("reg", "cup", "playin", "post")             # games that count (preseason exhibitions left out)
WINS_SERIES = re.compile(r"^\s*(\S+)\s+wins series\s+(\d+)\s*-\s*(\d+)", re.I)


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


_num = FL._num


def _fmt(v, f: str | None) -> str:
    v = _num(v)
    if v is None:
        return ""
    if f in ("+1", "+2"):
        d = int(f[1])
        return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v):.{d}f}"
    m = "−" if v < 0 else ""
    a = abs(v)
    if f == "3":
        return m + (f"{a:.3f}".replace("0.", ".", 1) if a < 1 else f"{a:.3f}")
    if f in ("pct1", "pct"):
        return m + f"{a * 100:.1f}%"
    if f == "1":
        return m + f"{a:.1f}"
    if f in ("0", "int"):
        return m + f"{a:.0f}"
    return m + f"{a:g}"


def _signed(v, d: int = 1) -> str:
    return _fmt(v, f"+{d}")


def _rank(values: dict, higher: bool = True) -> dict:
    """{key: rank} with 1 the best (ties share the better rank)."""
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


def _nice_day(s: str) -> str:
    d = date.fromisoformat(str(s)[:10])
    return f"{('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[d.weekday()]} {d.day} {('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[d.month - 1]} {d.year}"


def _side_p(g: dict, tid: str, key: str = "model") -> float | None:
    p = _num((g.get(key) or {}).get("p_home"))
    if p is None:
        return None
    return round(p if str(g.get("home")) == tid else 1 - p, 4)


def games_of(data: Path, league: str, season: int, lg_index: dict) -> list[dict]:
    """The season's games: schedule.json, with index.json's today / next / last (written later in the same build, or
    by a newer build) laid over by id."""
    by = {}
    for g in (_read(data / league / str(season) / "schedule.json") or {}).get("games") or []:
        by[str(g.get("id"))] = g
    for k in ("last_games", "today", "next_games"):
        for g in lg_index.get(k) or []:
            if int(g.get("season") or season) == int(season):
                by[str(g.get("id"))] = dict(by.get(str(g.get("id"))) or {}, **g)
    return list(by.values())


def _comp(g: dict, lgname: str) -> str:
    st = g.get("stype")
    if st == "post":
        return str((g.get("series") or {}).get("round") or "Playoffs").replace("Playoff Series", "Playoffs")
    if st == "playin":
        return "Play-in"
    if st == "cup":
        return f"{lgname} Cup final"
    return lgname


def results_of(games: list[dict], tid: str, asof: datetime) -> list[dict]:
    """The team's finished games at `asof`, oldest first, as follow.py results (exhibitions left out)."""
    out = []
    for g in games:
        if g.get("stype") not in COUNTS or g.get("status") != "post" or tid not in (str(g.get("home")), str(g.get("away"))):
            continue
        t = FL._dt(g.get("date"))
        hs, as_ = _num(g.get("hs")), _num(g.get("as"))
        if t is None or t > asof or hs is None or as_ is None:
            continue
        home = str(g.get("home")) == tid
        us, them = (hs, as_) if home else (as_, hs)
        out.append({"start": str(g.get("date")), "res": "W" if us > them else "L", "p": _side_p(g, tid), "us": int(us), "them": int(them),
                    "home": home, "opp": str(g.get("away") if home else g.get("home")), "id": str(g.get("id")), "stype": g.get("stype"), "g": g})
    out.sort(key=lambda r: r["start"])
    return out


def upcoming_of(games: list[dict], tid: str, asof: datetime, n: int = 3) -> list[dict]:
    out = []
    for g in games:
        if g.get("stype") not in COUNTS or g.get("status") not in ("pre", None) or tid not in (str(g.get("home")), str(g.get("away"))):
            continue
        t = FL._dt(g.get("date"))
        if t is None or t <= asof:
            continue
        out.append((t, g))
    out.sort(key=lambda x: x[0])
    return [g for _, g in out[:n]]


def _series_sig(series: list[dict], fmt: dict | None, h: str, a: str) -> dict | None:
    """featured.py's sig.series for a playoff game (build_hardwood.py _series_sig)."""
    rounds = (fmt or {}).get("series") or []
    for x in series:
        t = [str(v) for v in x.get("teams") or []]
        if sorted(t) == sorted([h, a]) and "wins series" not in str(x.get("summary") or "").lower():
            w = x.get("wins") or {}
            wh, wa = int(w.get(h) or 0), int(w.get(a) or 0)
            k = int(x["rnum"]) - 1 if isinstance(x.get("rnum"), int) else 0
            best = x.get("best_of") or (rounds[min(k, len(rounds) - 1)] if rounds else 7)
            return {"game": wh + wa + 1, "wins": [wh, wa], "best_of": best, "name": str(x.get("round") or "")}
    return None


def _series_winner(x: dict, abbr_to_tid: dict) -> str | None:
    if x.get("winner"):
        return str(x["winner"])
    m = WINS_SERIES.match(str(x.get("summary") or ""))
    if m and abbr_to_tid.get(m.group(1).upper()):
        return abbr_to_tid[m.group(1).upper()]
    w = x.get("wins") or {}
    best = int(x.get("best_of") or 0)
    if best:
        for t, n in w.items():
            if int(n or 0) >= best // 2 + 1:
                return str(t)
    return None


def postseason_series(season_json: dict, games: list[dict], asof: datetime) -> list[dict]:
    """season.json's postseason series, each brought up to date with the finished games (index.json's last games can
    be newer than season.json): wins recounted from the games, winner set once a side reaches best_of // 2 + 1."""
    out = []
    by_pair: dict = {}
    for g in games:
        if g.get("stype") == "post" and g.get("status") == "post" and _num(g.get("hs")) is not None:
            t = FL._dt(g.get("date"))
            if t is not None and t <= asof:
                by_pair.setdefault(frozenset((str(g.get("home")), str(g.get("away")))), {})[str(g.get("id"))] = g
    for x in ((season_json.get("postseason") or {}).get("series") or []):
        y = dict(x)
        tm = [str(v) for v in x.get("teams") or []]
        gs = by_pair.get(frozenset(tm)) or {}
        if len(tm) == 2 and gs:
            w = {tm[0]: 0, tm[1]: 0}
            for g in gs.values():
                hs, as_ = float(g["hs"]), float(g["as"])
                win = str(g.get("home")) if hs > as_ else str(g.get("away"))
                if win in w:
                    w[win] += 1
            if sum(w.values()) >= sum(int(v or 0) for v in (x.get("wins") or {}).values()):
                y["wins"] = w
            best = int(x.get("best_of") or 0)
            if best and not y.get("winner"):
                for t, n in y["wins"].items():
                    if n >= best // 2 + 1:
                        y["winner"] = t
        out.append(y)
    return out


def _record_at(log_rows: list[dict], n: int) -> tuple[int, int] | None:
    rs = [r for r in sorted(log_rows or [], key=lambda r: str(r.get("date"))) if r.get("res") in ("W", "L")]
    if len(rs) < n or n <= 0:
        return None
    w = sum(1 for r in rs[:n] if r["res"] == "W")
    return w, n - w


def _first_season(data: Path, league: str, tid: str, seasons: list[int]) -> int | None:
    """The first season on disk with the team in season.json (for "the first title in franchise history")."""
    for s in sorted(seasons):
        sj = _read(data / league / str(s) / "season.json") or {}
        if tid in {str(k) for k in (sj.get("teams") or {})}:
            return s
    return None


def build(data: Path, league: str = "nba", now: datetime | None = None, out_dir: Path | None = None) -> dict:
    """Write data/follow/<league>/<tid>.json for every team of the league's current season; returns write_cards' summary."""
    from oddsmarkets.common import featured as FT
    data = Path(data)
    asof = now or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=timezone.utc)
    idx = _read(data / "index.json") or {}
    li = (idx.get("leagues") or {}).get(league) or {}
    season = li.get("current_season")
    if not season:
        raise ValueError(f"no current season for {league} in index.json")
    season = int(season)
    lgname = li.get("name") or LEAGUE_NAME.get(league, league.upper())
    sdir = data / league / str(season)
    sj = _read(sdir / "season.json") or {}
    tj = (_read(sdir / "teams.json") or {}).get("teams") or {}
    vj = _read(sdir / "value.json") or {}
    games = games_of(data, league, season, li)
    info = {str(k): dict(v) for k, v in (li.get("teams") or sj.get("teams") or {}).items()}
    for k, v in (sj.get("teams") or {}).items():
        info.setdefault(str(k), dict(v))
    abbr_to_tid = {str(v.get("abbr") or "").upper(): t for t, v in info.items() if v.get("abbr")}
    teams = sorted(info)
    if not teams:
        raise ValueError(f"no teams for {league} {season}")
    sim = ((sj.get("sim") or {}).get("teams") or {}) if isinstance(sj.get("sim"), dict) else {}
    R = sj.get("ratings") or {}
    power = [str(r[0]) for r in sj.get("power") or [] if r and _num(r[1]) is not None]
    if not power:
        power = [t for t, _ in sorted(((t, _num((R.get(t) or {}).get("net"))) for t in teams), key=lambda x: -(x[1] if x[1] is not None else -99)) if _ is not None]
    rating_rank = {t: i + 1 for i, t in enumerate(power)}
    LB = sj.get("league_block") or {}
    prof_spec = (LB.get("profile") or {}).get("metrics") or []
    lteams = LB.get("teams") or {}
    race = LB.get("race") or {}
    series = postseason_series(sj, games, asof)
    # the champion: index.json's list, else the decided final round
    champ_t, final_x = None, None
    for c in li.get("champions") or []:
        if int(c[0]) == season:
            champ_t = str(c[1])
    # the last round: rkey "finals", else a round named "Finals" / "NBA Finals" / "WNBA Finals" (never "Semi-finals"
    # or "Conference Finals")
    finals = [x for x in series if x.get("rkey") == "finals"] or \
        [x for x in series if re.fullmatch(r"(?:w?nba\s+)?finals", str(x.get("round") or "").strip(), re.I)]
    if finals:
        final_x = finals[-1]
        champ_t = champ_t or _series_winner(final_x, abbr_to_tid)
    raw_phase = str(li.get("phase") or sj.get("phase") or "regular")
    phase = "offseason" if champ_t else PHASE.get(raw_phase, "season")
    final = phase in ("offseason", "postseason")
    # standings rows, the place in the conference, and every team's record
    rows, place = {}, {}
    for grp, rs in (sj.get("standings") or {}).items():
        rs = sorted(rs, key=lambda r: (_num(r.get("seed")) or 99, _num(r.get("gb")) or 0))
        for i, r in enumerate(rs, 1):
            t = str(r.get("team"))
            rows[t] = r
            place[t] = (i, len(rs), grp)
    played = {t: int((rows.get(t) or {}).get("w") or 0) + int((rows.get(t) or {}).get("l") or 0) for t in teams}
    pct_all = {t: _num((rows.get(t) or {}).get("pct")) for t in teams if played.get(t, 0) >= 10}
    pct_rank = _rank(pct_all)

    def split_rank(side: int):
        v = {}
        for t in teams:
            x = (rows.get(t) or {}).get("home" if side == 0 else "away") or []
            if len(x) >= 2 and (x[0] + x[1]) >= 5:
                v[t] = x[0] / (x[0] + x[1])
        return _rank(v)
    home_rank, away_rank = split_rank(0), split_rank(1)
    # the race log (the 7-day change and the pre-playoff call)
    rlog = (_read(data / league / "race_log.json") or {}).get(str(season)) or {}
    hist = _read(data / league / "history.json") or {}
    # the players: WAR from value.json (qualified), else HPM from the rosters
    cols = vj.get("cols") or []
    vrows = [dict(zip(cols, r)) for r in vj.get("rows") or []] if cols else []
    war_q = [r for r in vrows if _num(r.get("war")) is not None and r.get("q")]
    by_team_war: dict = {}
    for r in war_q:
        by_team_war.setdefault(str(r.get("team")), []).append(r)
    hpm_pool = []
    for t, x in tj.items():
        for p in x.get("roster") or []:
            if _num(p.get("hpm")) is not None and (_num(p.get("mpg")) or 0) >= 15 and (_num(p.get("gp")) or 0) >= 1:
                hpm_pool.append(float(p["hpm"]))
    hpm_pool.sort(reverse=True)
    war_pool = sorted((float(r["war"]) for r in war_q), reverse=True)
    prev_tj = None
    # the season's postseason teams, and the last race-log snapshot before the first playoff game (the title call)
    post_teams = sorted({str(t) for x in series for t in x.get("teams") or []})
    first_post = min((str(g.get("date")) for g in games if g.get("stype") == "post"), default=None)
    pre_call = {}
    if first_post and rlog.get("p_title"):
        # only a snapshot logged live counts as our call: a day the log rebuilt afterwards (_meta.rebuilt, before
        # _meta.live_from) was not published on that day
        meta = rlog.get("_meta") or {}
        rebuilt = set(meta.get("rebuilt") or [])
        live_from = str(meta.get("live_from") or "")
        days = sorted(d for d in rlog["p_title"] if d < first_post[:10] and d not in rebuilt and d >= live_from)
        if days:
            pre_call = {str(k): v for k, v in (rlog["p_title"][days[-1]] or {}).items()}
    next_od = None
    if phase == "offseason":
        nsch = (_read(data / league / str(season + 1) / "schedule.json") or {}).get("games") or []
        days = sorted(str(g.get("date"))[:10] for g in nsch if g.get("stype") == "reg" and g.get("date"))
        next_od = days[0] if days else None
    cards = {}
    for t in teams:
        ti = info.get(t) or {}
        r = rows.get(t) or {}
        s = sim.get(t) or {}
        pos, of, grp = place.get(t, (None, None, ti.get("conference")))
        short = ti.get("short") or ti.get("name")
        team = {"name": ti.get("name"), "short": short, "abbr": ti.get("abbr"), "colour": ti.get("colour"), "alt": ti.get("alt") or ti.get("alt_colour"),
                "href": f"#/{league}/team/{t}", "league": lgname, "group": grp}
        res = results_of(games, t, asof)
        reg_played = played.get(t, 0)
        rec = FL.record_text(r.get("w"), r.get("l")) if reg_played or phase != "preseason" else None
        st = None
        if pos and reg_played:
            gb = _num(r.get("gb"))
            st = {"pos": pos, "of": of, "group": grp, "gb": gb if gb else None,
                  "text": f"{FL.ordinal(pos)} in the {grp}" + (f", {gb:g} back" if gb and gb > 0 and phase == "season" else "")}
        rt = None
        net = _num((R.get(t) or {}).get("net"))
        if net is not None and t in rating_rank:
            rt = {"value": net, "text": _signed(net, 1), "rank": rating_rank[t], "of": len(rating_rank), "label": "Net rating"}
        now_blk = {"record": rec, "form": None if phase == "offseason" else FL.form_letters(res, asof), "standing": st, "rating": rt}
        sk = FL.streak_of(res, asof)
        if sk and phase != "offseason":
            now_blk["streak"] = f"{sk[0]}{sk[1]}"
        # chances: playoffs and the title in the season, the title alone in the playoffs, none once decided
        chances = []
        if phase != "offseason":
            alive = phase != "postseason" or not any(t in [str(v) for v in x.get("teams") or []] and x.get("winner") and str(x["winner"]) != t for x in series)
            keys = (("p_playoffs", "Playoffs"), ("p_title", "Title")) if phase in ("season", "preseason") else (("p_title", "Title"),)
            for key, lab in keys:
                p = _num(s.get(key))
                if p is None or (phase == "postseason" and not alive):
                    continue
                ser = {d: (v or {}).get(t) for d, v in (rlog.get(key) or {}).items() if isinstance(v, dict)}
                chances.append({"key": key, "label": lab, "p": round(p, 4), "d7": FL.change_since(ser, asof, 7), "_ser": ser})
        if len(chances) == 2 and chances[1]["p"] < 0.05:
            chances = chances[::-1]                        # a long shot's headline is the playoffs, not the title
        # next games
        nxt = []
        for g in (upcoming_of(games, t, asof) if phase != "offseason" else []):
            h, a = str(g.get("home")), str(g.get("away"))
            home = h == t
            o = a if home else h
            oi = info.get(o) or {}
            sh, sa = sim.get(h) or {}, sim.get(a) or {}
            sig = {"title": [sh.get("p_title"), sa.get("p_title")]}
            if g.get("stype") == "post":
                ser = _series_sig(series, sj.get("format"), h, a)
                if ser:
                    sig["series"] = ser
            else:
                sig["playoff"] = [sh.get("p_playoffs"), sa.get("p_playoffs")]
            fg = {"sport": SPORT, "league": lgname, "id": g.get("id"), "start": g.get("date"), "status": "pre", "home": h, "away": a,
                  "p_home": (g.get("model") or {}).get("p_home"), "sig": sig}
            sg = FT.significance(fg, asof)
            comp = _comp(g, lgname)
            sr = (g.get("series") or {})
            if g.get("stype") == "post" and sig.get("series"):
                comp = f"{comp} · Game {sig['series']['game']}"
            nxt.append({"id": str(g.get("id")), "start": g.get("date"), "home": home,
                        "opp": {"name": oi.get("short") or oi.get("name") or o, "abbr": oi.get("abbr"), "colour": oi.get("colour"), "rank": rating_rank.get(o)},
                        "comp": comp, "p": _side_p(g, t), "mkt": _side_p(g, t, "market"), "why": sg["reasons"][:2], "href": f"#/{league}/game/{g.get('id')}",
                        "_score": sg["score"], "_short": oi.get("short"), "_reasons": sg["reasons"], "_sr": sr})
        # the season line: the title, how the playoffs ended, or the record so far
        champ = champ_t == t
        live_x = None
        if phase == "postseason":
            live_x = next((x for x in series if t in [str(v) for v in x.get("teams") or []] and not x.get("winner") and len(x.get("teams") or []) == 2), None)
        out_in = None
        for x in series:
            tm = [str(v) for v in x.get("teams") or []]
            if t in tm and x.get("winner") and str(x["winner"]) != t:
                w = x.get("wins") or {}
                opp = tm[1 - tm.index(t)]
                out_in = {"round": str(x.get("round") or "playoffs").replace("Playoff Series", "playoffs"), "us": int(w.get(t) or 0), "them": int(w.get(opp) or 0),
                          "opp": (info.get(opp) or {}).get("short") or opp}
        line = None
        ru, fres = None, None
        if champ and final_x:
            tm = [str(v) for v in final_x.get("teams") or []]
            ru = tm[1 - tm.index(t)] if t in tm and len(tm) == 2 else None
            w = final_x.get("wins") or {}
            fres = [int(w.get(t) or 0), int(w.get(ru) or 0)] if ru else None
        ev_long = f"{lgname} Finals"
        if champ:
            ro = (info.get(ru) or {}).get("short") if ru else None
            line = f"Won the {season} {ev_long}" + (f", {fres[0]}{FL.DASH}{fres[1]} over the {ro}." if fres and ro else ".")
        elif out_in:
            line = f"{'Season over: ' if phase == 'offseason' else ''}out in the {out_in['round']}, {out_in['us']}{FL.DASH}{out_in['them']} to the {out_in['opp']}."
            line = line[0].upper() + line[1:]
        elif live_x and rec:
            w = live_x.get("wins") or {}
            tm = [str(v) for v in live_x.get("teams") or []]
            opp = tm[1 - tm.index(t)]
            us, them = int(w.get(t) or 0), int(w.get(opp) or 0)
            on = (info.get(opp) or {}).get("short") or opp
            rd = str(live_x.get("round") or "the playoffs").replace("Playoff Series", "the playoffs")
            line = f"{rec} in the regular season. {rd}: " + (f"level {us}{FL.DASH}{them} with the {on}." if us == them else
                                                              f"{'lead' if us > them else 'trail'} the {on} {us}{FL.DASH}{them}.")
        elif final and rec:
            missed = bool(post_teams) and t not in post_teams
            line = f"Season over: {rec}{', ' + st['text'] if st else ''}." + (" Missed the playoffs." if missed else "")
        elif rec and reg_played:
            line = f"{rec}{', ' + st['text'] if st else ''}."
        elif phase == "preseason" and _num(s.get("exp_w")) is not None:
            line = f"Projected {s['exp_w']:.0f}{FL.DASH}{(_num(s.get('exp_l')) or 0):.0f} in our preseason simulation."
        note = None
        if not nxt:
            if phase == "offseason":
                note = f"Off-season. Opening night {season + 1}: {_nice_day(next_od)}." if next_od else f"Off-season. The {season + 1} schedule is not out yet."
            elif phase == "postseason" and (out_in or (post_teams and t not in post_teams)):
                note = "Season over."
            elif live_x:
                note = "The next game of the series is not on the schedule yet."
            else:
                note = "No games in the next few days."
        last = None
        if res:
            x = res[-1]
            oi = info.get(x["opp"]) or {}
            last = {"id": x["id"], "start": x["start"], "home": x["home"], "opp": {"name": oi.get("short") or oi.get("name") or x["opp"], "abbr": oi.get("abbr"), "colour": oi.get("colour")},
                    "score": [x["us"], x["them"]], "res": x["res"], "p": x["p"], "upset": FL.upset_flag(x["p"], x["res"]),
                    "comp": _comp(x["g"], lgname), "href": f"#/{league}/game/{x['id']}"}
        # the profile: the league block's percentiles on the team spec (style metrics left out)
        lt = lteams.get(t) or {}
        pc, vals = lt.get("pct") or {}, lt.get("vals") or {}
        prof_rows = [{"id": m["id"], "label": m.get("label") or m["id"], "pct": int(round(pc[m["id"]])), "text": _fmt(vals.get(m["id"]), m.get("fmt"))}
                     for m in prof_spec if _num(pc.get(m.get("id"))) is not None and not m.get("style")]
        prof_rows.sort(key=lambda x: -x["pct"])
        profile = None
        if len(prof_rows) >= 5:
            profile = {"strong": prof_rows[:3], "weak": sorted(prof_rows[3:], key=lambda x: x["pct"])[:2]}
        elif len(prof_rows) >= 2:
            profile = {"strong": [x for x in prof_rows if x["pct"] >= 50][:3], "weak": sorted([x for x in prof_rows if x["pct"] < 50], key=lambda x: x["pct"])[:2]}
        # top players: WAR (qualified), else HPM among rotation players
        players, top_ctx = [], None
        tw = sorted(by_team_war.get(t) or [], key=lambda p: -float(p["war"]))
        if tw:
            players = [{"name": p.get("name"), "pos": p.get("pos"), "metric": "WAR", "value": round(float(p["war"]), 1), "text": f"{float(p['war']):.1f}",
                        "href": f"#/{league}/player/{p.get('id')}"} for p in tw[:2]]
            p0 = tw[0]
            rk = 1 + sum(1 for v in war_pool if v > float(p0["war"]))
            top_ctx = {"name": p0.get("name"), "text": f"{float(p0['war']):.1f}", "metric": "WAR", "rank": rk, "of": len(war_pool),
                       "tied": sum(1 for v in war_pool if v == float(p0["war"])) > 1, "pool": f"{lgname} players"}
        else:
            ro = sorted((p for p in ((tj.get(t) or {}).get("roster") or []) if _num(p.get("hpm")) is not None and (_num(p.get("mpg")) or 0) >= 15),
                        key=lambda p: -float(p["hpm"]))
            players = [{"name": p.get("name"), "pos": p.get("pos"), "metric": "HPM", "value": round(float(p["hpm"]), 1), "text": _signed(p["hpm"], 1),
                        "href": f"#/{league}/player/{p.get('id')}"} for p in ro[:2]]
            if ro and sum(1 for g in res if g["stype"] == "reg") >= 5:
                p0 = ro[0]
                rk = 1 + sum(1 for v in hpm_pool if v > float(p0["hpm"]))
                top_ctx = {"name": p0.get("name"), "text": _signed(p0["hpm"], 1), "metric": "HPM", "rank": rk, "of": len(hpm_pool),
                           "tied": sum(1 for v in hpm_pool if v == float(p0["hpm"])) > 1, "pool": f"{lgname} rotation players"}
        # ── the facts
        ctx = {"name": ti.get("name"), "short": short, "the": True, "phase": phase, "final": final and not live_x, "league_name": f"the {lgname}", "results": res}
        pr = []
        min_gp = int((LB.get("profile") or {}).get("min_gp") or 10)
        if prof_spec:
            for m in prof_spec:
                if m.get("id") == "model_net" or m.get("style"):
                    continue                      # the rating has its own fact; style is not better or worse
                if not m.get("model") and reg_played < min_gp:
                    continue                      # box-score rates wait for the league block's sample floor
                vals_all = {x: _num(((lteams.get(x) or {}).get("vals") or {}).get(m["id"])) for x in teams}
                rk = _rank(vals_all, higher=m.get("dir", "higher") != "lower")
                if t in rk and _tie_size(rk, t) <= 2:
                    pr.append({"label": m.get("label") or m["id"], "rank": rk[t], "of": len(rk), "tied": _tie_size(rk, t) > 1,
                               "text": _fmt(vals.get(m["id"]), m.get("fmt")), "model": bool(m.get("model"))})
        ctx["pctl"] = pr
        if pct_rank.get(t) in (1, 2) and rec and _tie_size(pct_rank, t) == 1:
            ctx["best_record"] = {"record": rec, "scope": "league", "where": f"the {lgname}", "rank": pct_rank[t]}
        elif pos == 1 and rec and grp and reg_played >= 10:
            ctx["best_record"] = {"record": rec, "scope": "group", "where": grp}
        hr_, ar_ = r.get("home") or [None, None], r.get("away") or [None, None]
        sp = {"of": len(home_rank), "league": f"the {lgname}"}
        if t in home_rank and _tie_size(home_rank, t) <= 2:
            sp["home"] = {"record": FL.record_text(*hr_[:2]), "rank": home_rank[t], "tied": _tie_size(home_rank, t) > 1}
        if t in away_rank and _tie_size(away_rank, t) <= 2:
            sp["away"] = {"record": FL.record_text(*ar_[:2]), "rank": away_rank[t], "tied": _tie_size(away_rank, t) > 1}
        ctx["split"] = sp
        luck = lt.get("luck") or {}
        if _num(luck.get("d")) is not None and reg_played >= 10:
            ctx["luck"] = {"d": luck["d"], "unit": "wins", "basis": "their points scored and allowed say they deserved"}
        rc = race.get(t) or {}
        if rc.get("sos") and phase == "season" and len(rc["sos"]) >= 3 and rc["sos"][2]:
            avg, rk, left = rc["sos"][:3]
            ctx["sos"] = {"rank": rk, "of": len(teams), "left": left, "where": f"the {lgname}", "text": _signed(avg, 1)}
        mg = (s.get("magic") or {}).get("postseason") if isinstance(s.get("magic"), dict) else None
        if phase == "season" and _num(mg) is not None and 0 < mg <= 10:
            ctx["clinch"] = {"magic": int(mg), "what": "a playoff place"}
        ctx["chances"] = [{"label": "title" if c["key"] == "p_title" else "playoff", "series": c.pop("_ser")} for c in chances]
        if nxt:
            g0 = nxt[0]
            # a "big one" needs stakes: the playoffs, or a regular season far enough in for a place to hang on it
            big = phase == "postseason" or reg_played >= 20
            ctx["next"] = {"start": g0["start"], "opp": {"short": g0["_short"], "name": g0["opp"]["name"]}, "p": g0["p"], "score": g0["_score"] if big else None,
                           "reasons": g0["_reasons"], "rivalry": FL.rivalry(short, g0["_short"])}
        if top_ctx:
            ctx["players"] = [top_ctx]
        # this season against last
        if reg_played >= 10 or phase == "offseason":
            if prev_tj is None:
                prev_tj = (_read(data / league / str(season - 1) / "teams.json") or {}).get("teams") or {}
            plog = (prev_tj.get(t) or {}).get("log") or []
            w, l_ = int(r.get("w") or 0), int(r.get("l") or 0)
            if phase == "offseason" and plog:
                pw = sum(1 for x in plog if x.get("res") == "W")
                pl = sum(1 for x in plog if x.get("res") == "L")
                if pw + pl:
                    ctx["vs_last"] = {"now": [w, l_], "last": [pw, pl], "season_last": season - 1, "full": True}
            elif plog and phase == "season":
                at = _record_at(plog, w + l_)
                if at:
                    ctx["vs_last"] = {"now": [w, l_], "last": list(at), "season_last": season - 1}
        if champ:
            c = {"event": lgname, "season": season, "result": fres, "opp": (info.get(ru) or {}).get("short") if ru else None}
            prior = [int(x[0]) for x in (hist.get("champions") or li.get("champions") or []) if str(x[1]) == t and int(x[0]) < season]
            cover = min((int(x[0]) for x in (hist.get("champions") or li.get("champions") or [])), default=None)
            if prior:
                c["since"] = max(prior)
            else:
                fs = _first_season(data, league, t, [int(x) for x in (li.get("seasons") or [])])
                data_first = int(hist.get("first_season") or 0)
                if fs and cover and fs > data_first and fs >= cover:
                    c["first_title"] = True
                    c["seasons"] = season - fs + 1
            if pre_call and _num(pre_call.get(t)) is not None:
                pool = {k: v for k, v in pre_call.items() if k in post_teams and _num(v) is not None} or pre_call
                c["pre_p"] = float(pre_call[t])
                c["pre_rank"] = 1 + sum(1 for v in pool.values() if float(v) > float(pre_call[t]))
                c["pre_n"] = len(pool)
            ctx["champion"] = c
        if rt:
            ctx["rating"] = {"rank": rt["rank"], "of": rt["of"], "text": rt["text"], "unit": "per 100 possessions"}
        fx = FL.facts(ctx, asof)
        if any(f["kind"] == "rating_move" for f in fx):
            fx = [f for f in fx if f["kind"] != "rating"]  # one line on our ratings is enough
        for g in nxt:
            for k in ("_score", "_short", "_reasons", "_sr"):
                g.pop(k, None)
        champion = {"event": lgname, "season": season, "text": line} if champ else None
        cards[t] = FL.make_card(site=SITE, sport=SPORT, scope=league, ident=t, team=team, asof=asof, phase=phase, season=season,
                                now=now_blk, chances=chances, next_games=nxt, next_note=note, last=last, line=line, profile=profile,
                                facts=fx, players=players, champion=champion)
    return FL.write_cards(out_dir or (data / "follow"), league, cards)


def main(argv=None) -> int:
    import argparse
    from oddsmarkets.basketball import analytics as an
    ap = argparse.ArgumentParser(description="Write the Hardwood's follow cards from the payloads on disk")
    ap.add_argument("--data", default=None)
    ap.add_argument("--leagues", nargs="*", default=["nba", "wnba"])
    ap.add_argument("--now", default=None, help="ISO build clock (default now)")
    a = ap.parse_args(argv)
    data = Path(a.data) if a.data else an.data_root()
    now = FL._dt(a.now) if a.now else None
    for lg in a.leagues:
        s = build(data, lg, now)
        print(f"{lg}: {s['n']} cards, {s['bytes'] / 1024:.0f} KB, largest {s['max']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
