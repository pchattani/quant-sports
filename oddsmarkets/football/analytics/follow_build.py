"""The Quant Footballer's follow cards (My Teams): one small card per club or national team at
data/follow/club/<tid>.json, keyed by the Sofascore team id (the same id in every league and cup: `site:club:<tid>`).

The schema and the fact engine are oddsmarkets/common/follow.py; this module only gathers what the football build has
already written (no new fetching):

    competitions.json            the competitions and their current seasons (a card for every side with a current season
                                 in any of them: about 1,550 clubs and 220 national teams)
    clubs_index.json             names, colours, the home league
    clubs/<tid>.json             every match in every competition (form, the last result, the next three fixtures with our
                                 home / draw / away chance), the season rows (record, place, points, a cup's stage), titles
    <comp>/teams.json            league and cup names -> team id (the league files below are keyed by name)
    <comp>/table.json            standings, the bands (European places, relegation), the season's results (home and away)
    <comp>/probs.json            our title, band and relegation chances; a cup's chance to win it
    <comp>/strength.json         the schedule still to play (sos_remaining)
    <comp>/team_stats.json       per-match averages: the profile's league percentiles, computed here
    <comp>/history.json          our title and relegation chances run by run (the 7-day change)
    pool.json, nations.json      our rating on one scale for every club (the cross-league rank) and national team
    forecast_log.json            our chance frozen before kick-off (the last result's "we gave them N%")
    value/season.json, players.json  the top two players by GAR this season, and their rank in the league

    build(data_root, now=None) -> {"n", "bytes", "max", "ids"}     (python -m oddsmarkets.football.analytics.follow_build)

No look-ahead: a result counts only once its kick-off is at or before the build clock, the last result's chance is the
forecast frozen before kick-off (forecast_log.json; none when the log no longer holds it), a fixture is "next" only
while it has not started, and the 7-day change compares two history snapshots taken on those days.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from oddsmarkets.common import featured as FT
from oddsmarkets.common import follow as FL

log = logging.getLogger(__name__)

SITE, SPORT, SCOPE = "site", "football", "club"
LEAGUE_KINDS = ("league", "conference", "playoff", "liga", "torneo")
# the leagues read with "the" in a sentence ("2nd in the Premier League"; "1st in LaLiga")
WITH_THE = {"premier-league", "bundesliga", "eredivisie", "brasileirao", "saudi-pro-league", "belgian-pro-league"}
# the profile: the predictive team metrics of team_stats.json (process over style; fouls, distance and the like left out)
PROFILE = ("xg", "xga", "xg_diff", "shots", "shots_ag", "sot", "xg_per_shot", "big_chances", "box_touches", "final_third",
           "poss", "pass_pct", "recoveries", "aerial_pct", "ground_pct", "conv", "save_pct")
SIGNED = {"xg_diff"}
MIN_PROFILE_MATCHES = 3


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _num(x):
    return FL._num(x)


def _rows(j: dict | None) -> list[dict]:
    j = j or {}
    f = j.get("fields") or []
    return [dict(zip(f, r)) for r in j.get("rows") or []]


def _fmt(v, f: str | None, signed: bool = False) -> str:
    v = _num(v)
    if v is None:
        return ""
    if f == "pct":
        return f"{v:.0f}%"
    if f == "int":
        return f"{v:.0f}"
    s = f"{abs(v):.{1 if f == '1' else 2}f}"
    if signed:
        return ("+" if v > 0 else "−" if v < 0 else "±") + s
    return ("−" if v < 0 else "") + s


def record(w, d, l) -> str | None:
    if _num(w) is None or _num(l) is None:
        return None
    return f"W{int(w)} D{int(d or 0)} L{int(l)}"


def _rank(values: dict, higher: bool = True) -> dict:
    """{key: rank} with 1 the best (ties share the better rank)."""
    xs = sorted(((v, k) for k, v in values.items() if _num(v) is not None), key=lambda t: -t[0] if higher else t[0])
    out, prev, prev_rank = {}, None, 0
    for i, (v, k) in enumerate(xs, 1):
        r = prev_rank if prev is not None and v == prev else i
        out[k] = r
        prev, prev_rank = v, r
    return out


def _pctl(values: dict, higher: bool = True) -> dict:
    """{key: percentile 0-100} within the group: the share below plus half the ties (the best of 20 is 98)."""
    xs = [v for v in values.values() if _num(v) is not None]
    n = len(xs)
    out = {}
    for k, v in values.items():
        if _num(v) is None or not n:
            continue
        below = sum(1 for x in xs if (x < v if higher else x > v))
        eq = sum(1 for x in xs if x == v) - 1
        out[k] = int(round(100 * (below + 0.5 * eq + 0.5) / n))
    return out


def _ties(rank: dict) -> set:
    seen: dict = {}
    for k, r in rank.items():
        seen.setdefault(r, []).append(k)
    return {k for ks in seen.values() if len(ks) > 1 for k in ks}


def _when(m: dict):
    return FL._dt(m.get("date") or m.get("start"))


def _side(model: dict | None, home: bool):
    """(our win, draw) from a home / draw / away chance, from this side's view."""
    m = model or {}
    h, d, a = _num(m.get("h")), _num(m.get("d")), _num(m.get("a"))
    if h is None or a is None:
        return None, None
    return round(h if home else a, 4), (round(d, 4) if d is not None else None)


def _res(m: dict) -> str | None:
    r = str(m.get("res") or "")[:1].upper()
    return r if r in ("W", "D", "L") else None


class _Comp:
    """One competition's current-season files, keyed by team id."""

    def __init__(self, data: Path, c: dict):
        self.slug = c["slug"]
        self.c = c
        self.name = c.get("name") or self.slug
        self.short = c.get("short_name") or self.name
        self.kind = c.get("kind")
        self.scope = c.get("scope")
        self.is_league = self.kind in LEAGUE_KINDS
        d = data / self.slug
        tm = (_read(d / "teams.json") or {}).get("teams") or {}
        self.tid = {nm: str(v.get("team_id")) for nm, v in tm.items() if isinstance(v, dict) and v.get("team_id") is not None}
        self.name_of = {t: nm for nm, t in self.tid.items()}
        pr = _read(d / "probs.json") or {}
        self.probs = {self.tid.get(r.get("team")): r for r in pr.get("teams") or [] if self.tid.get(r.get("team"))}
        self.table = {}
        self.bands = []
        self.of = None
        self.fixtures = []
        self.mpt = None
        self.strength = {}
        self.stats = {}
        self.metrics = {}
        self.series = {"title": {}, "band": {}, "relegation": {}, "alt": {}}
        self.band_key = None
        self.alt = None          # a second title the history logs (Argentina: the Tabla Anual), from table.json
        self.decided = None      # {"tid", "event"}: the league's table title already won (decided_title)
        if not self.is_league:
            br = _read(d / "bracket.json") or {}
            self.p_cup = {self.tid.get(k): v for k, v in (br.get("p_cup") or {}).items() if self.tid.get(k)}
            for t, r in self.probs.items():
                if _num(r.get("p_cup")) is not None:
                    self.p_cup.setdefault(t, r["p_cup"])
            return
        self.p_cup = {}
        tb = _read(d / "table.json") or {}
        hk = (tb.get("hist_keys") or {}).get("title") or "title"
        if hk != "title":
            done = bool(tb.get("total_games")) and tb.get("games_played") == tb.get("total_games")
            self.alt = {"hist": hk, "key": tb.get("title_key") or "p_" + hk,
                        "label": tb.get("title_label") or tb.get("label") or hk.title(),
                        "name": tb.get("label") or hk.title(), "season": tb.get("season"), "done": done}
        self.bands = tb.get("bands") or []
        self.fixtures = tb.get("fixtures") or []
        self.mpt = tb.get("matches_per_team")
        groups = []
        if tb.get("standings"):
            # a torneo league's table is its current stage's ("3rd in the Clausura")
            groups.append((((tb.get("stage") or {}).get("label") or "") if self.kind == "torneo" else "", tb["standings"]))
        for g, rs in (tb.get("conferences") or {}).items():
            groups.append((g, rs))
        for g, rs in groups:
            for r in rs or []:
                t = self.tid.get(r.get("team"))
                if t and t not in self.table:
                    self.table[t] = dict(r, _group=g, _of=len(rs))
        self.decided = decided_title(self, tb)
        st = _read(d / "strength.json") or {}
        self.strength = {self.tid.get(r.get("team")): r for r in st.get("rows") or [] if self.tid.get(r.get("team"))}
        ts = _read(d / "team_stats.json") or {}
        self.metrics = {m["key"]: m for m in ts.get("metrics") or [] if m.get("key")}
        self.stats = {self.tid.get(nm): (v or {}).get("season") or {} for nm, v in (ts.get("teams") or {}).items() if self.tid.get(nm)}
        hist = _read(d / "history.json") or {}
        daily = hist.get("daily") or []
        for snap in daily + (hist.get("snapshots") or []):
            ts_ = snap.get("ts") or snap.get("d")
            if not ts_:
                continue
            if snap.get("band_key"):
                self.band_key = self.band_key or snap["band_key"]
            is_daily = "d" in snap
            for key in ("title", "band", "relegation", "alt"):
                src = key
                if self.alt:
                    # the daily race log names the second title "title"; the hourly snapshots keep both under their
                    # own names. Merging them read Boca's Clausura 24% against last week's Tabla Anual 71% (-47).
                    if key == "title" and is_daily:
                        continue
                    if key == "alt":
                        src = "title" if is_daily else self.alt["hist"]
                elif key == "alt":
                    continue
                block = snap.get(src)
                if not isinstance(block, dict):
                    continue
                for nm, t in self.tid.items():
                    self.series[key].setdefault(t, {})[ts_] = float(block.get(nm) or 0.0)

    def where(self) -> str:
        return ("the " if self.slug in WITH_THE else "") + self.name


def _cup_full(comp: _Comp, league_of: dict) -> bool:
    """A national cup's chances mean something once its big clubs are in the draw: the clubs of a followed league hold
    at least half of the chance to win it (an early-rounds bracket, before the top flight enters, does not)."""
    if comp.scope == "international" or comp.c.get("family") != "domestic":
        return True
    return sum(float(p or 0) for t, p in comp.p_cup.items() if league_of.get(t)) >= 0.5


def clinched_first(rows: list[dict], mpt, complete: bool) -> dict | None:
    """The table's leader once first place is certain: every match played, or more points than any other side can
    still reach (3 a match left). Arithmetic only: a simulated 100% is not a clinch."""
    rows = [r for r in rows or [] if r.get("pts") is not None]
    if len(rows) < 2:
        return None
    rows = sorted(rows, key=lambda r: (r.get("pos") or 999))
    lead = rows[0]
    if complete:
        return lead if lead.get("pos") == 1 else None
    if not mpt:
        return None
    best_other = max(int(r["pts"]) + 3 * max(int(mpt) - int(r.get("played") or 0), 0) for r in rows[1:])
    return lead if int(lead["pts"]) > best_other else None


def decided_title(comp, tb: dict) -> dict | None:
    """A table title already won: a straight league's title (clinched or finished) and MLS's Supporters' Shield
    (the overall table once the regular season is played). Leagues whose title is a play-off, a final or a stage
    (Liga MX, the torneo leagues, Argentina's Clausura) never count their table here."""
    complete = bool(tb.get("total_games")) and tb.get("games_played") == tb.get("total_games")
    if comp.kind == "league":
        lead = clinched_first(tb.get("standings"), tb.get("matches_per_team"), complete)
        event = comp.name
    elif comp.kind == "conference":
        lead = clinched_first(tb.get("overall"), tb.get("matches_per_team"), complete)
        event = "Supporters' Shield" if comp.slug == "mls" else (tb.get("overall_label") or comp.name)
    else:
        return None
    tid = comp.tid.get((lead or {}).get("team"))
    return {"tid": tid, "event": event} if tid else None


def yr_won(d: dict, comps: dict) -> list[str]:
    """The titles won this season (clubs/<tid>.json years[0].won), friendlies aside."""
    yr = (d.get("years") or [{}])[0] if d.get("years") else {}
    return [w for w in (yr.get("won") or []) if w in comps and w != "friendlies"]


def _national(club: dict, cur_rows: list[dict], comps: dict) -> bool:
    """National team: flagged so, and with no current season in a club competition (a club that once met a national
    team in a friendly carries the flag: Fiorentina, Lazio, Valencia)."""
    if not club.get("national"):
        return False
    return not any((comps.get(s.get("comp")) or {}).get("scope") == "club" for s in club.get("seasons") or [])


def build(data: Path, now: datetime | None = None, out_dir: Path | None = None) -> dict:
    """Write data/follow/club/<tid>.json for every side with a current season in a followed competition."""
    data = Path(data)
    asof = now or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=timezone.utc)
    comps_l = (_read(data / "competitions.json") or {}).get("competitions") or []
    comps = {c["slug"]: c for c in comps_l if c.get("slug")}
    current = {c["slug"]: str((c.get("current_season") or {}).get("sid")) for c in comps_l
               if c.get("ok") and (c.get("current_season") or {}).get("status") == "current"}
    if not current:
        raise ValueError("no competition with a current season in competitions.json")
    C = {s: _Comp(data, comps[s]) for s in current}
    ci = {str(r.get("id")): r for r in _rows(_read(data / "clubs_index.json"))}
    pool = _read(data / "pool.json") or {}
    n_pool = len(pool.get("clubs") or [])
    # the pool's rows by team id; a row without one by its competition's name -> id (the cup-only clubs)
    prow: dict = {}
    for r in pool.get("clubs") or []:
        t = str(r["team_id"]) if r.get("team_id") is not None else (C[r["comp"]].tid.get(r.get("team")) if r.get("comp") in C else None)
        if t and t not in prow:
            prow[t] = r
    nat = (_read(data / "nations.json") or {}).get("teams") or []
    nat_by_name = {r.get("team"): r for r in nat if r.get("team")}
    flog = _read(data / "forecast_log.json") or {}
    # value: this season's GAR (club football, or national-team football), the league each player plays in
    vp = {str(r.get("id")): r for r in _rows(_read(data / "value" / "players.json"))}
    vs = _rows(_read(data / "value" / "season.json"))
    by_tid: dict[str, list] = {}
    league_pool: dict[str, list] = {}
    intl_pool: list = []
    for r in vs:
        g = _num(r.get("gar"))
        if g is None or r.get("tid") is None:
            continue
        sc = r.get("scope")
        if sc in ("club", "intl"):
            by_tid.setdefault((sc, str(r["tid"])), []).append(r)
        if sc == "club":
            lg = (vp.get(str(r.get("id"))) or {}).get("league")
            if lg:
                league_pool.setdefault(lg, []).append(g)
        elif sc == "intl":
            intl_pool.append(g)
    for v in league_pool.values():
        v.sort(reverse=True)
    intl_pool.sort(reverse=True)

    # which clubs play in a followed league this season (their home league), for the cups' "big clubs in yet" test
    files = sorted((data / "clubs").glob("*.json"))
    clubs, league_of = {}, {}
    for f in files:
        d = _read(f)
        if not isinstance(d, dict) or d.get("id") is None:
            continue
        cur = [s for s in d.get("seasons") or [] if current.get(s.get("comp")) == str(s.get("sid"))]
        if not cur:
            continue
        t = str(d["id"])
        clubs[t] = (d, cur)
        lg = next((s["comp"] for s in cur if s.get("kind") == "league" and s.get("comp") == d.get("home")), None) or \
            next((s["comp"] for s in cur if s.get("kind") == "league"), None)
        if lg:
            league_of[t] = lg
    cup_full = {s: _cup_full(c, league_of) for s, c in C.items() if not c.is_league}
    # home and road records in each league (table.json's results)
    splits: dict[str, dict] = {}
    for s, c in C.items():
        if not c.is_league:
            continue
        rec: dict[str, dict] = {}
        for fx in c.fixtures:
            if not fx.get("done") or _num(fx.get("hg")) is None or _num(fx.get("ag")) is None or fx.get("stage", "league") != "league":
                continue
            t_ = FL._dt(fx.get("date"))
            if t_ is None or t_ > asof:
                continue
            for side, us, them in (("home", fx["hg"], fx["ag"]), ("away", fx["ag"], fx["hg"])):
                t = c.tid.get(fx.get(side))
                if not t:
                    continue
                x = rec.setdefault(t, {"home": [0, 0, 0], "away": [0, 0, 0]})[side]
                x[0 if us > them else 1 if us == them else 2] += 1
        ppg = {side: {t: (3 * v[side][0] + v[side][1]) / sum(v[side]) for t, v in rec.items() if sum(v[side]) >= 3} for side in ("home", "away")}
        splits[s] = {"rec": rec, "rank": {side: _rank(ppg[side]) for side in ppg}, "of": len(c.table)}

    def opp_info(tid) -> dict:
        r = ci.get(str(tid)) or {}
        rk = (prow.get(str(tid)) or {}).get("rank")
        if r.get("national") and not r.get("home"):
            rk = (nat_by_name.get(r.get("name")) or {}).get("rank")
        return {"colour": r.get("colour"), "rank": rk}

    cards = {}
    for t, (d, cur) in sorted(clubs.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        info = ci.get(t) or {}
        national = _national(d, cur, comps)
        name = d.get("name") or info.get("name")
        if not name:
            continue
        lg_slug = league_of.get(t) if not national else None
        L = C.get(lg_slug) if lg_slug else None
        lrow = next((s for s in cur if s.get("comp") == lg_slug), None) if L else None
        cur_names = [C[s["comp"]].name for s in cur if s.get("comp") in C]
        team = {"name": name, "short": name, "colour": d.get("colour") or info.get("colour"), "alt": d.get("alt") or info.get("alt"),
                "href": f"#/club/{t}", "league": "National team" if national else (L.name if L else (cur_names[0] if cur_names else None))}
        # the matches, all competitions
        ms = [m for m in d.get("matches") or [] if _when(m) is not None]
        fin = sorted((m for m in ms if m.get("status") == "finished" and _res(m) and _when(m) <= asof), key=_when)
        results = []
        for m in fin:
            p, _ = (None, None)
            fl = flog.get(str(m.get("id")))
            if isinstance(fl, list) and len(fl) >= 4 and FL._dt(fl[3]) is not None and FL._dt(fl[3]) <= asof:
                p = _num(fl[0] if m.get("home") else fl[2])
            results.append({"start": m.get("date"), "res": _res(m), "p": p, "_m": m})
        upcoming = sorted((m for m in ms if m.get("status") in ("scheduled", "notstarted") and _when(m) > asof), key=_when)
        # standing, record, rating
        tr = L.table.get(t) if L else None
        st = None
        rec_txt = None
        if tr and _num(tr.get("w")) is not None:
            rec_txt = record(tr.get("w"), tr.get("d"), tr.get("l"))     # the table's own record, beside its place and points
        elif lrow and _num(lrow.get("w")) is not None:
            rec_txt = record(lrow.get("w"), lrow.get("d"), lrow.get("l"))
        if tr:
            pos, of, grp = tr.get("pos"), tr.get("_of"), tr.get("_group") or None
            lead = max((_num(x.get("pts")) or 0) for x in L.table.values() if (x.get("_group") or None) == grp) if L.table else None
            pts = _num(tr.get("pts"))
            gb = (lead - pts) if lead is not None and pts is not None else None
            if rec_txt is None:
                rec_txt = record(tr.get("w"), tr.get("d"), tr.get("l"))
            if pos:
                where = f"the {grp} Conference" if grp in ("Eastern", "Western") else (f"the {grp}" if grp else L.where())
                st = {"pos": pos, "of": of, "group": grp, "gb": gb if gb else None,
                      "text": f"{FL.ordinal(pos)} in {where}, {int(pts) if pts is not None else 0} pts" + (f", {gb:g} behind" if gb and gb > 0 else "")}
                if grp:
                    team["group"] = grp
        rt = None
        if national:
            nr = nat_by_name.get(name) or {}
            if _num(nr.get("strength")) is not None and nr.get("rank"):
                rt = {"value": round(float(nr["strength"]), 4), "text": f"{float(nr['strength']):.2f}", "rank": nr["rank"], "of": len(nat), "label": "Our rating"}
        else:
            pr_ = prow.get(t) or {}
            if _num(pr_.get("strength")) is not None and pr_.get("rank"):
                rt = {"value": round(float(pr_["strength"]), 4), "text": f"{float(pr_['strength']):.2f}", "rank": pr_["rank"], "of": n_pool, "label": "Our rating"}
        form = FL.form_letters(results, asof)
        sk = FL.streak_of(results, asof)
        now_blk = {"record": rec_txt, "form": form or None, "streak": f"{sk[0]}{sk[1]}" if sk else None, "standing": st, "rating": rt}
        # chances: the league's title, its first "up" band and relegation; the cups still alive. The headline goes last.
        chances, ctx_ch = [], []
        if L:
            pr = L.probs.get(t) or (tr or {})
            fav = L.c.get("favourite_label") or "Title"
            title_key = "p_cup" if L.kind in ("conference", "playoff") and _num(pr.get("p_cup")) is not None else "p_title"
            p_title = _num(pr.get(title_key))
            bands = pr.get("bands") or {}
            up = next((b for b in L.bands if b.get("kind") == "up"), None)
            dn = [b for b in L.bands if b.get("kind") == "down"]
            p_up = _num(bands.get(up["key"])) if up else None
            p_dn = sum(float(bands.get(b["key"]) or 0) for b in dn) if dn else None
            if L.kind == "torneo":
                # Colombia, Uruguay, Peru: relegation is the promedio or the aggregate table, not a band of the stage
                p_dn = _num(pr.get("p_relegation"))
                dn = [{"label": "Relegation"}] if p_dn is not None else []
            rows_c = []
            if p_title is not None and title_key == "p_title" and L.kind == "league" and (L.decided or {}).get("tid") == t:
                p_title = None           # won already: the card carries the title, not a 100% chance
            if p_title is not None:
                ser = L.series["title"].get(t) if title_key == "p_title" else None
                rows_c.append({"key": "p_title", "label": "Title" if fav in ("Title", "Winner") else fav, "p": round(p_title, 4),
                               "d7": FL.change_since(ser, asof, 7) if ser else None, "_imp": 3 if p_title >= 0.03 else 0})
                if ser:
                    ctx_ch.append({"label": "title", "series": ser})
            alt_p = _num(pr.get(L.alt["key"])) if L.alt else None
            if alt_p is not None and 0.0005 < alt_p and not (L.alt["done"] and alt_p >= 0.9995):
                ser = L.series["alt"].get(t)
                rows_c.append({"key": L.alt["key"], "label": L.alt["label"], "p": round(alt_p, 4),
                               "d7": FL.change_since(ser, asof, 7) if ser else None, "_imp": 2.8 if alt_p >= 0.03 else 0})
            if up and p_up is not None and 0.0005 < p_up:
                ser = L.series["band"].get(t) if L.band_key == up["key"] else None
                rows_c.append({"key": "p_" + up["key"], "label": up.get("label") or "Top", "p": round(p_up, 4),
                               "d7": FL.change_since(ser, asof, 7) if ser else None, "_imp": 2 if 0.05 <= p_up <= 0.97 else 0})
            p_lib = _num(pr.get("p_libertadores")) if L.kind == "torneo" else None
            if p_lib is not None and 0.0005 < p_lib:
                rows_c.append({"key": "p_libertadores", "label": "Libertadores", "p": round(p_lib, 4), "d7": None,
                               "_imp": 2 if 0.05 <= p_lib <= 0.97 else 0})
            if dn and p_dn is not None and p_dn >= 0.005:
                ser = L.series["relegation"].get(t)
                rows_c.append({"key": "p_rel", "label": dn[0].get("label") if len(dn) == 1 else "Drop", "p": round(p_dn, 4),
                               "d7": FL.change_since(ser, asof, 7) if ser else None, "_imp": 2.5 if p_dn >= 0.05 else 0})
                if ser:
                    ctx_ch.append({"label": "relegation", "series": ser})
            chances = rows_c
        cups = []
        for s in cur:
            c = C.get(s.get("comp"))
            if not c or c.is_league or not cup_full.get(c.slug):
                continue
            p = _num(c.p_cup.get(t))
            if p is not None and p > 0.0005:
                cups.append({"key": "p_cup_" + c.slug, "label": f"{c.short} title", "p": round(p, 4), "d7": None, "_imp": 1 + p})
        cups.sort(key=lambda x: -x["p"])
        chances = chances + cups[:2]
        chances.sort(key=lambda x: x["_imp"])
        for x in chances:
            x.pop("_imp", None)
        chances = chances[-4:]
        # next fixtures, all competitions
        nxt = []
        for m in upcoming[:3]:
            c = C.get(m.get("comp"))
            cname = (c.short if c else (comps.get(m.get("comp")) or {}).get("short_name")) or m.get("comp")
            home = bool(m.get("home"))
            p, pdraw = _side(m.get("model"), home)
            oi = opp_info(m.get("opp_tid"))
            tp = None
            if c:
                src = (lambda x: _num((c.probs.get(x) or {}).get("p_title"))) if c.is_league else (lambda x: _num(c.p_cup.get(x)) if cup_full.get(c.slug) else None)
                a, b = src(t), src(str(m.get("opp_tid")))
                if a is not None or b is not None:
                    tp = [a or 0.0, b or 0.0] if home else [b or 0.0, a or 0.0]
            rnd = m.get("round") if isinstance(m.get("round"), str) else None
            stage = FT.stage_of({"sig": {"round": rnd}}) or ("knockout" if m.get("stage") == "playoff" else None)
            riv = FL.rivalry(name, m.get("opp"))
            mod = m.get("model") or {}
            g = {"sport": SPORT, "league": cname, "id": m.get("id"), "start": m.get("date"), "status": "pre",
                 "p_home": mod.get("h"), "p_draw": mod.get("d"), "p_away": mod.get("a"),
                 "sig": {"comp": m.get("comp"), "stage": stage, "title": tp, "rivalry": riv}}
            sg = FT.significance(g, asof)
            nxt.append({"id": str(m.get("id")), "start": m.get("date"), "home": home,
                        "opp": {"name": m.get("opp"), "colour": oi.get("colour"), "rank": oi.get("rank")},
                        "comp": cname, "p": p, "p_draw": pdraw, "why": sg["reasons"][:2], "href": f"#/match/{m.get('comp')}/{m.get('id')}",
                        "_score": sg["score"], "_reasons": sg["reasons"], "_riv": riv})
        # the last result, with our chance frozen before kick-off
        last = None
        if results:
            x = results[-1]
            m = x["_m"]
            c = C.get(m.get("comp"))
            oi = opp_info(m.get("opp_tid"))
            last = {"id": str(m.get("id")), "start": m.get("date"), "home": bool(m.get("home")),
                    "opp": {"name": m.get("opp"), "colour": oi.get("colour")}, "score": [m.get("gf"), m.get("ga")], "res": x["res"],
                    "p": x["p"], "upset": FL.upset_flag(x["p"], x["res"]),
                    "comp": (c.short if c else (comps.get(m.get("comp")) or {}).get("short_name")) or m.get("comp"),
                    "href": f"#/match/{m.get('comp')}/{m.get('id')}"}
        # the season line
        line = None
        if st and rec_txt and not yr_won(d, comps):
            line = f"{rec_txt}, {st['text']}."       # a champion's card carries its title chip, not the table again
        else:
            # a cup is alive with a fixture to come, or when its last tie was won (the next round not drawn yet); out
            # when its last tie was lost (the club file's `through`, else the result of a single match)
            live_cups = [C[s["comp"]] for s in cur if s.get("comp") in C and not C[s["comp"]].is_league]
            alive, out_of = [], []
            for c in live_cups:
                if any(m.get("comp") == c.slug for m in upcoming):
                    alive.append(c)
                    continue
                lm = next((x["_m"] for x in reversed(results) if x["_m"].get("comp") == c.slug), None)
                if lm is None:
                    continue
                thr = lm.get("through")
                won = bool(thr) if thr is not None else (_res(lm) == "W" if _res(lm) != "D" else None)
                if won is True:
                    alive.append(c)
                elif won is False and (lm.get("stage") != "league"):
                    out_of.append(c)
            if alive:
                line = "Still in the " + " and the ".join(c.name for c in alive[:2]) + "."
            elif out_of and not national:
                line = "Out of the " + out_of[0].name + "."
        # titles won this season (a super cup, a finished league)
        champion = None
        yr = (d.get("years") or [{}])[0] if d.get("years") else {}
        won = yr_won(d, comps)
        if won:
            w = won[0]
            cs = comps.get(w) or {}
            sname = (cs.get("current_season") or {}).get("season") or yr.get("era")
            champion = {"event": cs.get("name") or w, "season": yr.get("era") or sname, "text": f"Won the {yr.get('era')} {cs.get('name') or w}."}
        if champion is None:
            for s in cur:
                c = C.get(s.get("comp"))
                if c and c.is_league and (c.decided or {}).get("tid") == t:
                    season = (comps.get(c.slug, {}).get("current_season") or {}).get("season") or yr.get("era")
                    champion = {"event": c.decided["event"], "season": season, "text": f"Won the {season} {c.decided['event']}."}
                    break
        if champion is None:
            # a second title decided before the season ends (every Tabla Anual match played, first place certain)
            for s in cur:
                c = C.get(s.get("comp"))
                if c and c.is_league and c.alt and c.alt["done"] and (_num((c.probs.get(t) or {}).get(c.alt["key"])) or 0) >= 0.9995:
                    season = c.alt.get("season") or yr.get("era")
                    champion = {"event": c.alt["name"], "season": season, "text": f"Won the {season} {c.alt['name']}."}
                    break
        note = None
        if not nxt:
            note = "No fixtures scheduled yet." if not national else "No fixtures until the next international window."
        # the profile: league percentiles on the predictive team metrics (team_stats.json)
        profile, pctl_ctx = None, []
        if L and L.stats.get(t) and (_num(L.stats[t].get("matches")) or 0) >= MIN_PROFILE_MATCHES:
            peers = {x: v for x, v in L.stats.items() if (_num(v.get("matches")) or 0) >= MIN_PROFILE_MATCHES}
            prof_rows = []
            for key in PROFILE:
                meta = L.metrics.get(key) or {}
                if not meta or _num(L.stats[t].get(key)) is None:
                    continue
                higher = not meta.get("lower")
                vals = {x: _num(v.get(key)) for x, v in peers.items()}
                pc = _pctl(vals, higher)
                rk = _rank(vals, higher)
                if t not in pc:
                    continue
                txt = _fmt(L.stats[t][key], meta.get("fmt"), key in SIGNED)
                prof_rows.append({"id": key, "label": meta.get("label") or key, "pct": pc[t], "text": txt})
                pctl_ctx.append({"label": meta.get("label") or key, "rank": rk[t], "of": len(rk), "tied": t in _ties(rk), "text": txt,
                                 "model": key in ("xg", "xga", "xg_diff")})
            prof_rows.sort(key=lambda x: -x["pct"])
            if len(prof_rows) >= 5:
                profile = {"strong": prof_rows[:3], "weak": sorted(prof_rows[3:], key=lambda x: x["pct"])[:2]}
        # top players by GAR this season (club football, or the national team's)
        sc = "intl" if national else "club"
        roster = sorted(by_tid.get((sc, t)) or [], key=lambda r: -float(r["gar"]))
        players = []
        for r in roster[:2]:
            pv = vp.get(str(r.get("id"))) or {}
            nm = r.get("name") or pv.get("name")
            if not nm:
                continue
            players.append({"name": nm, "pos": pv.get("role"), "metric": "GAR", "value": round(float(r["gar"]), 2),
                            "text": f"{float(r['gar']):.1f}", "href": f"#/player/{r.get('id')}"})
        # ── the facts
        ctx = {"name": name, "short": name, "the": False, "phase": "season", "final": False,
               "league_name": L.where() if L else None, "results": results, "chances": ctx_ch, "pctl": pctl_ctx}
        if L and tr and tr.get("pos") == 1 and not tr.get("_group") and rec_txt:
            ctx["best_record"] = {"record": rec_txt, "scope": "league", "where": L.where()}
        if L and lg_slug in splits:
            sp = splits[lg_slug]
            rr = sp["rec"].get(t) or {}
            ctx["split"] = {"of": sp["of"], "league": L.where(),
                            "home": {"record": record(*rr["home"]) if rr else None, "rank": sp["rank"]["home"].get(t)},
                            "away": {"record": record(*rr["away"]) if rr else None, "rank": sp["rank"]["away"].get(t)}}
        if L and L.strength.get(t) and _num(L.strength[t].get("sos_remaining")) is not None and L.mpt:
            sos = {x: _num(r.get("sos_remaining")) for x, r in L.strength.items()}
            rk = _rank(sos, higher=True)
            left = int(L.mpt) - int(_num(L.strength[t].get("played")) or 0)
            if t in rk and left >= 5:
                ctx["sos"] = {"rank": rk[t], "of": len(rk), "left": left, "where": L.where(),
                              "text": f"{float(L.strength[t]['sos_remaining']):.2f} points a game"}
        if nxt:
            g0 = nxt[0]
            ctx["next"] = {"start": g0["start"], "opp": {"short": g0["opp"]["name"], "name": g0["opp"]["name"]}, "p": g0["p"],
                           "score": g0["_score"], "reasons": g0["_reasons"], "rivalry": g0["_riv"]}
        if roster:
            r0 = roster[0]
            pv = vp.get(str(r0.get("id"))) or {}
            pl_pool = intl_pool if national else league_pool.get(lg_slug or pv.get("league") or "", [])
            g0v = float(r0["gar"])
            if pl_pool and (r0.get("name") or pv.get("name")):
                rk = 1 + sum(1 for v in pl_pool if v > g0v)
                tied = sum(1 for v in pl_pool if v == g0v) > 1
                where = "national-team players" if national else f"{L.name if L else 'league'} players"
                ctx["players"] = [{"name": r0.get("name") or pv.get("name"), "text": f"{g0v:.1f}", "metric": "GAR", "rank": rk,
                                   "of": len(pl_pool), "tied": tied, "pool": where}]
        if champion:
            ctx["champion"] = {"event": champion["event"], "season": champion["season"]}
        if rt and rt["rank"] <= rt["of"] / 2:          # the top half: a rating line worth a fact; the card shows it anyway
            ctx["rating"] = {"rank": rt["rank"], "of": rt["of"], "text": rt["text"], "unit": "points a game against an average side"}
        fx = FL.facts(ctx, asof)
        for f in fx:
            # follow.py's next-game lines are written for "the Brewers"; a football side has no article
            f["text"] = f["text"].replace(" against the ", " against ")
        for g in nxt:
            for k in ("_score", "_reasons", "_riv"):
                g.pop(k, None)
        cards[t] = FL.make_card(site=SITE, sport=SPORT, scope=SCOPE, ident=t, team=team, asof=asof, phase="season", season=None,
                                now=now_blk, chances=chances, next_games=nxt, next_note=note, last=last, line=line, profile=profile,
                                facts=fx, players=players, champion=champion)
    return FL.write_cards(out_dir or (data / "follow"), SCOPE, cards)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Write The Quant Footballer's follow cards from the payloads on disk")
    ap.add_argument("--data", default=str(Path(__file__).resolve().parents[3] / "docs" / "site" / "data"))
    ap.add_argument("--now", default=None, help="ISO build clock (default now)")
    a = ap.parse_args(argv)
    s = build(Path(a.data), FL._dt(a.now) if a.now else None)
    print(f"club: {s['n']} cards, {s['bytes'] / 1024:.0f} KB, largest {s['max']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
