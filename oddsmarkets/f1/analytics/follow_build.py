"""The Paddock's follow cards (My Teams): one small card per driver at data/follow/driver/<id>.json and per constructor at
data/follow/team/<id>.json, for the current season.

The schema and the fact engine are oddsmarkets/common/follow.py; this module only gathers what the Paddock build has
already written (no new fetching):

    index.json                    the current season, the drivers (code, team) and the constructors (colours)
    <Y>/season.json               standings, the championship simulation (p_title, magic numbers, clinched and
                                  eliminated), title_history (the 7-day change), Elo, the calendar, points by round
    <Y>/races/<r>.json            finished rounds' results (streaks, the team-mate fight, the last race); the next
                                  round's forecast (pre_quali, or post_quali once qualifying is in): win and podium
    <Y>/drivers.json, teams.json  this season's catalogue: percentiles for the profile, ranks for the facts
    <Y-1>/season.json             points by round last season ("at this point of 2025")

    build(data_root, now=None) -> {"driver": summary, "team": summary}      (python -m oddsmarkets.f1.analytics.follow_build)

The title wording is literal. A driver at 100% in our simulation who has not clinched is "in all 20,000 of our
simulated seasons, but not yet mathematically champion"; only `clinched` (the magic number reached) or a finished
season says champion.

No look-ahead: a round counts once its race start is at or before the build clock; the next round's forecast is used
only when it was generated before the clock; the 7-day change compares two title_history snapshots taken on those
days.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL

log = logging.getLogger(__name__)

SITE, SPORT = "paddock", "f1"
# the profile and the league-rank facts: the drivers' and constructors' headline sets (docs/_design/metrics/f1.json)
# (key, label, format, unit)
D_PROFILE = (("driver_effect", "Race driver rating", "3", "%"), ("quali_driver_effect", "Qualifying driver rating", "3", "%"),
             ("race_pace", "Race pace v field", "3", " s"), ("race_h2h", "Races ahead of the team-mate", "prob", ""),
             ("quali_h2h", "Qualifying ahead of the team-mate", "prob", ""), ("team_points_share", "Share of team points", "prob", ""),
             ("points_per_race", "Points per race", "p2", ""), ("lap1_gain", "Lap-1 places gained", "2", ""),
             ("tyre_mgmt", "Tyre management", "1", ""), ("net_overtakes", "Net overtakes per race", "2", ""))
D_PCTL = ("driver_effect", "quali_driver_effect", "race_pace", "points_per_race", "lap1_gain")
# the league-rank facts' own wording ("The best race pace in F1 this season"); points per race says nothing the
# standings do not, so it is never shown as a "worst"
PCTL_LABEL = {"driver_effect": "race driver rating", "quali_driver_effect": "qualifying driver rating", "race_pace": "race pace",
              "points_per_race": "points per race", "lap1_gain": "lap-1 gain", "car_race_pace": "car on race pace",
              "car_quali_pace": "car on qualifying pace", "pit_under_2500": "share of stops under 2.5 s"}
NO_WORST = {"points_per_race"}
T_PROFILE = (("car_race_pace", "Car race pace", "3", "%"), ("car_quali_pace", "Car qualifying pace", "3", "%"),
             ("points_per_race", "Points per race", "p2", ""), ("both_points_rate", "Both cars in the points", "prob", ""),
             ("dnf_rate", "DNF rate", "prob", ""), ("pit_under_2500", "Stops under 2.5 s", "prob", ""),
             ("strategy_gain", "Places gained through the stops", "2", ""), ("tyre_mgmt", "Tyre management", "1", ""))
T_PCTL = ("car_race_pace", "car_quali_pace", "points_per_race", "pit_under_2500")


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


_num = FL._num


def _fmt(v, f, unit="") -> str:
    v = _num(v)
    if v is None:
        return ""
    if f == "prob":
        return f"{v * 100:.0f}%"
    sign = "−" if v < 0 else ("+" if f in ("3", "2") and v > 0 else "")
    nd = {"3": 3, "2": 2, "p2": 1, "1": 1, "0": 0}.get(str(f), 2)
    return f"{sign}{abs(v):.{nd}f}{unit}"


def _rank(values: dict, higher: bool = True) -> dict:
    xs = sorted(((v, k) for k, v in values.items() if _num(v) is not None), key=lambda t: -t[0] if higher else t[0])
    out, prev, prev_rank = {}, None, 0
    for i, (v, k) in enumerate(xs, 1):
        r = prev_rank if prev is not None and v == prev else i
        out[k] = r
        prev, prev_rank = v, r
    return out


def _short_race(name: str | None) -> str:
    s = re.sub(r" Grand Prix.*$", "", str(name or ""))
    return re.sub(r"^Grand Prix (of )?", "", s) or str(name or "")


def _nice_day(d: datetime) -> str:
    return f"{('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[d.weekday()]} {d.day} {('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[d.month - 1]}"


def _race_start(r: dict) -> datetime | None:
    d, t = str(r.get("date") or ""), str(r.get("time") or "")
    if len(d) != 10:
        return None
    return FL._dt(d + "T" + (t.rstrip("Z") if t else "12:00:00") + "Z")


def _shown(p: float, c: dict) -> float:
    """A title chance as the card shows it: never 100% before the title is clinched (the site's own pages say >99.9%)."""
    return round(p, 4) if c.get("clinched") or p < 0.9999 else 0.9999


def _surname(name: str) -> str:
    parts = str(name or "").split()
    return parts[-1] if parts else str(name or "")


def _possessive(s: str) -> str:
    return s + ("’" if s.endswith("s") else "’s")


def _select(cands: list[dict], phase: str, ctx: dict, asof) -> list[dict]:
    """follow.py's candidates for its subject-free templates (the league ranks, the 7-day swing) plus this module's
    own lines, ranked as follow.facts ranks them: best first, no two of a kind, no repeated text, at most five."""
    allc = FL.candidates(ctx, asof) + cands
    if phase == "offseason":
        allc = [c for c in allc if c["kind"] not in FL.LIVE_KINDS]
    seen_k, seen_t, out = set(), set(), []
    for c in sorted(allc, key=lambda c: (-c["score"], FL.KINDS.index(c["kind"]) if c["kind"] in FL.KINDS else 99)):
        t = " ".join(c["text"].split()).strip()
        if c["score"] < FL.MIN_SCORE or c["kind"] in seen_k or t.lower() in seen_t:
            continue
        seen_k.add(c["kind"])
        seen_t.add(t.lower())
        out.append({"kind": c["kind"], "text": t, "score": round(c["score"], 1)})
        if len(out) >= FL.MAX_FACTS:
            break
    return out


def build(data: Path, now: datetime | None = None, out_dir: Path | None = None) -> dict:
    """Write data/follow/driver/<id>.json and data/follow/team/<id>.json for the current season."""
    data = Path(data)
    asof = now or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=timezone.utc)
    idx = _read(data / "index.json") or {}
    y = int(idx.get("current_season") or asof.year)
    sj = _read(data / str(y) / "season.json") or {}
    if not sj.get("standings"):
        raise ValueError(f"no standings in {y}/season.json")
    prev = _read(data / str(y - 1) / "season.json") or {}
    dcat = _read(data / str(y) / "drivers.json") or {}
    tcat = _read(data / str(y) / "teams.json") or {}
    dmeta = {m["key"]: m for m in dcat.get("metrics") or [] if m.get("key")}
    tmeta = {m["key"]: m for m in tcat.get("metrics") or [] if m.get("key")}
    D = {str(k): v for k, v in (dcat.get("drivers") or {}).items()}
    TC = {str(k): v for k, v in (tcat.get("teams") or {}).items()}
    teams_i = dict(idx.get("teams") or {})
    for k, v in (sj.get("teams") or {}).items():
        teams_i.setdefault(k, v)
    drivers_i = dict(idx.get("drivers") or {})
    names = sj.get("names") or {}
    champ = sj.get("championship") or {}
    n_sims = int(champ.get("n_sims") or 20000)
    finished = bool(sj.get("finished"))
    done = int(sj.get("rounds_done") or 0)
    total = int(sj.get("rounds_total") or len(sj.get("calendar") or []))
    phase = "offseason" if finished else ("preseason" if done == 0 else "season")
    meta = ((idx.get("seasons_meta") or {}).get(str(y)) or {})
    # finished rounds at the clock: the results by round
    cal = sorted(sj.get("calendar") or [], key=lambda r: int(r.get("round") or 0))
    played, results = [], {}
    for r in cal:
        st = _race_start(r)
        if r.get("status") == "done" and st is not None and st <= asof:
            rj = _read(data / str(y) / "races" / f"{r['round']}.json") or {}
            if rj.get("results"):
                played.append(r)
                results[int(r["round"])] = rj["results"]
    left = total - len(played)
    nxt = next((r for r in cal if r.get("status") != "done" and (_race_start(r) or asof) > asof), None)
    fc, fc_kind = {}, None
    if nxt:
        rj = _read(data / str(y) / "races" / f"{nxt['round']}.json") or {}
        f = rj.get("forecast") or {}
        for kind in ("post_quali", "pre_quali"):
            blk = f.get(kind) or {}
            gen = FL._dt(blk.get("generated_at") or f.get("generated_at"))
            if blk.get("drivers") and gen is not None and gen <= asof:
                fc, fc_kind = blk, kind
                break
    nshort = _short_race(nxt.get("name")) if nxt else ""
    nstart = _race_start(nxt) if nxt else None
    # standings
    dst = {str(r["driver"]): r for r in (sj.get("standings") or {}).get("drivers") or []}
    tst = {str(r["team"]): r for r in (sj.get("standings") or {}).get("constructors") or []}
    elo = {k: _num((v or {}).get("elo")) for k, v in (sj.get("elo") or {}).items()}
    elo_rank = _rank({k: v for k, v in elo.items() if k in dst})
    car = {t: _num(((TC.get(t) or {}).get("values") or {}).get("car_race_pace")) for t in tst}
    car_rank = _rank(car, higher=False)
    th = sorted(sj.get("title_history") or [], key=lambda h: str(h.get("as_of") or ""))

    def series(kind: str, key: str) -> dict:
        out = {}
        for h in th:
            p = _num(((h.get(kind) or {}).get(key) or {}).get("p_title"))
            if p is not None and h.get("as_of"):
                out[str(h["as_of"])] = p
        cur = _num(((champ.get(kind) or {}).get(key) or {}).get("p_title"))
        if cur is not None and sj.get("updated_at") and FL._dt(sj["updated_at"]) <= asof:
            out[str(sj["updated_at"])] = cur
        return out

    def prev_at(kind: str, key: str) -> float | None:
        pr = ((prev.get("progression") or {}).get(kind) or {}).get(key)
        n = len(played)
        if not pr or n <= 0 or len(pr) < n:
            return None
        return _num(pr[n - 1])

    leader_d = min(dst.values(), key=lambda r: r.get("pos") or 99) if dst else None
    leader_t = min(tst.values(), key=lambda r: r.get("pos") or 99) if tst else None
    second_d = next((r for r in dst.values() if r.get("pos") == 2), None)
    second_t = next((r for r in tst.values() if r.get("pos") == 2), None)
    mpl = champ.get("max_points_left") or {}

    def title_facts(who: str, plural: bool, kind: str, cid: str, row: dict, lead: dict | None, second: dict | None, what: str, out: list):
        c = (champ.get(kind) or {}).get(cid) or {}
        p = _num(c.get("p_title"))
        has, is_, wins = ("have", "are", "win") if plural else ("has", "is", "wins")
        pos = row.get("pos")
        if finished and pos == 1:
            out.append({"kind": "champion", "score": 100, "text": f"{y} {what} champion{'s' if plural else ''}."})
            return
        if c.get("clinched"):
            tail = f" with {left} race{'s' if left != 1 else ''} left" if left else ""
            out.append({"kind": "clinch", "score": 96, "text": f"{who} {has} clinched the {y} {what} title{tail}."})
        elif p is not None and p >= 0.9995:
            mg = _num(c.get("magic"))
            out.append({"kind": "clinch", "score": 90,
                        "text": f"{who} {wins} the {what} title in all {n_sims:,} of our simulated seasons, but {has} not clinched it: it is not yet mathematically decided"
                                + (f", and {mg:.0f} more points would settle it whatever the others do." if mg else ".")})
        elif c.get("eliminated") and pos and pos <= 6:
            out.append({"kind": "clinch", "score": 26, "text": f"{who} {is_} mathematically out of the {what} title fight."})
        if pos == 1 and second and not finished:
            gap = (_num(row.get("points")) or 0) - (_num(second.get("points")) or 0)
            out.append({"kind": "best_record", "score": 64, "text": f"{who} lead{'' if plural else 's'} the {what} championship by {gap:.0f} points" +
                        (f" with {left} race{'s' if left != 1 else ''} left." if left else ".")})
        elif pos and lead and pos <= 3 and not finished:
            gap = (_num(lead.get("points")) or 0) - (_num(row.get("points")) or 0)
            ln = (names.get(lead.get("driver")) if lead.get("driver") else (teams_i.get(lead.get("team")) or {}).get("name")) or ""
            out.append({"kind": "best_record", "score": 30, "text": f"{FL.ordinal(pos)} in the {what} championship, {gap:.0f} points behind {_surname(ln) if lead.get('driver') else ln}."})

    def vs_last(who: str, plural: bool, kind: str, key: str, pts, out: list):
        pv = prev_at(kind, key)
        if pv is None or _num(pts) is None or len(played) < 4:
            return
        d = float(pts) - pv
        if abs(d) < 30:
            return
        out.append({"kind": "vs_last", "score": 26 + min(30, abs(d) / 6) + (6 if d > 0 else 0),
                    "text": f"{who} {'have' if plural else 'has'} {float(pts):.0f} points after {len(played)} rounds, against {pv:.0f} at this point of {y - 1}."})

    def pctl_ctx(cat: dict, meta_: dict, keys: tuple, prof: tuple, cid: str) -> list:
        lab = {k: l for k, l, _f, _u in prof}
        fm = {k: (f, u) for k, _l, f, u in prof}
        qual = {k: v for k, v in cat.items() if v.get("qualified", True)}
        out = []
        for k in keys:
            m = meta_.get(k) or {}
            rk = _rank({x: (v.get("values") or {}).get(k) for x, v in qual.items()}, higher=not m.get("lower"))
            if cid in rk:
                out.append({"label": PCTL_LABEL.get(k) or lab.get(k, m.get("label") or k), "rank": rk[cid], "of": len(rk), "tied": list(rk.values()).count(rk[cid]) > 1,
                            "show_worst": k not in NO_WORST,
                            "text": _fmt(((cat.get(cid) or {}).get("values") or {}).get(k), *fm.get(k, ("2", ""))), "model": "effect" in k or "pace" in k})
        return out

    def profile_of(cat: dict, prof: tuple, cid: str) -> dict | None:
        x = cat.get(cid) or {}
        pc, vals = x.get("pct") or {}, x.get("values") or {}
        if not x.get("qualified", True):
            return None
        rows = [{"id": k, "label": lab, "pct": int(round(pc[k])), "text": _fmt(vals.get(k), f, u)} for k, lab, f, u in prof
                if _num(pc.get(k)) is not None and _num(vals.get(k)) is not None]
        if len(rows) < 5:
            return None
        srt = sorted(rows, key=lambda r: -r["pct"])
        return {"strong": srt[:3], "weak": sorted(srt[3:], key=lambda r: r["pct"])[:2]}

    # ── drivers
    dcards = {}
    ids = sorted(set(dst) | {k for k in drivers_i if k in dst or (drivers_i[k] or {}).get("team")})
    for d in ids:
        info = drivers_i.get(d) or {}
        row = dst.get(d) or {}
        nm = info.get("name") or names.get(d) or d.replace("_", " ").title()
        sur = _surname(nm)
        tm = row.get("team") or info.get("team")
        ti = teams_i.get(tm) or {}
        team = {"name": nm, "short": sur, "abbr": info.get("code"), "colour": ti.get("colour"), "alt": ti.get("alt"),
                "href": f"#/driver/{d}", "league": "F1", "group": ti.get("name")}
        pts = _num(row.get("points"))
        pos = row.get("pos")
        st = None
        if pos:
            st = {"pos": pos, "of": len(dst), "text": f"{FL.ordinal(pos)} in the championship"}
        rt = None
        if elo.get(d) is not None and d in elo_rank:
            rt = {"value": round(elo[d], 1), "text": f"{elo[d]:,.0f}", "rank": elo_rank[d], "of": len(elo_rank), "label": "Elo"}
        rec = f"{pts:.0f} pts" if pts is not None else None
        # finishing positions by round, newest last
        pos_by = []
        for r in played:
            rr = next((x for x in results[int(r["round"])] if str(x.get("driver")) == d), None)
            if rr is not None:
                pos_by.append((int(r["round"]), r, rr))
        now_blk = {"record": rec, "standing": st, "rating": rt}
        chances = []
        c = (champ.get("drivers") or {}).get(d) or {}
        pt = _num(c.get("p_title"))
        fd = ((fc.get("drivers") or {}).get(d) or {}) if fc else {}
        if phase != "offseason":
            if _num(fd.get("p_podium")) is not None and fd["p_podium"] >= 0.005:
                chances.append({"key": "p_podium", "label": f"{nshort} GP podium", "p": round(fd["p_podium"], 4), "d7": None})
            if _num(fd.get("p_win")) is not None and fd["p_win"] >= 0.005:
                chances.append({"key": "p_win", "label": f"{nshort} GP win", "p": round(fd["p_win"], 4), "d7": None})
            if pt is not None and (pt >= 0.005 or c.get("clinched")):
                chances.append({"key": "p_title", "label": "Title", "p": _shown(pt, c), "d7": FL.change_since(series("drivers", d), asof, 7)})
        note = None
        if nxt and nstart and phase != "offseason":
            bits = []
            if (_num(fd.get("p_win")) or 0) >= 0.005:
                bits.append(f"win {FL.pct_text(fd['p_win'])}")
            if (_num(fd.get("p_podium")) or 0) >= 0.005:
                bits.append(f"podium {FL.pct_text(fd['p_podium'])}")
            note = f"Next: the {nxt.get('name')}, {_nice_day(nstart)}." + (f" Our chance of a {', '.join(bits).replace(', ', ', a ')}" + (" (after qualifying)." if fc_kind == "post_quali" else ".") if bits else "")
        elif phase == "offseason":
            note = f"Season over. The {y + 1} season starts in March."
        line = None
        if pts is not None and pos:
            line = f"{FL.ordinal(pos)} in the {y} championship, {pts:.0f} points" + (f", {row.get('wins')} win{'s' if row.get('wins') != 1 else ''}" if row.get("wins") else "") + "."
        # facts
        mine: list = []
        title_facts(sur, False, "drivers", d, row, leader_d, second_d, "drivers’", mine)
        vs_last(sur, False, "drivers", d, pts, mine)
        if pos_by:
            def run(test):
                n = 0
                for _, _r, rr in reversed(pos_by):
                    if not test(rr):
                        break
                    n += 1
                return n
            w = run(lambda rr: rr.get("pos") == 1)
            pod = run(lambda rr: isinstance(rr.get("pos"), int) and rr["pos"] <= 3)
            pp = run(lambda rr: (_num(rr.get("points")) or 0) > 0)
            if w >= 2:
                mine.append({"kind": "streak", "score": 40 + 10 * w, "text": f"{sur} has won the last {w} Grands Prix."})
            elif pod >= 3:
                mine.append({"kind": "streak", "score": 30 + 6 * pod, "text": f"{sur} has been on the podium in each of the last {pod} races."})
            elif pp >= 5:
                mine.append({"kind": "streak", "score": 24 + 2 * pp, "text": f"{sur} has scored points in {pp} races in a row."})
            _, lr, lrr = pos_by[-1]
            p_ = lrr.get("pos")
            fin = f"P{p_}" if lrr.get("classified") and isinstance(p_, int) else "out"
            mine.append({"kind": "form_xp", "score": FL.MIN_SCORE + 4 if fin != "out" else FL.MIN_SCORE + 2,
                         "text": f"Last time out: {fin} at the {lr.get('name')}" + (f", from {lrr['grid']} on the grid." if _num(lrr.get("grid")) and fin != "out" else ".")})
        # the team-mate: races finished ahead (both started)
        mates = [k for k, r in dst.items() if r.get("team") == tm and k != d]
        best_m = None
        for m in mates:
            a = b = 0
            for rnd_, _r, rr in pos_by:
                mm = next((x for x in results[rnd_] if str(x.get("driver")) == m), None)
                if mm is None:
                    continue
                pa = rr.get("pos") if rr.get("classified") else 99
                pb = mm.get("pos") if mm.get("classified") else 99
                if pa == pb:
                    continue
                a += pa < pb
                b += pb < pa
            if a + b >= 4 and (best_m is None or a + b > best_m[1] + best_m[2]):
                best_m = (m, a, b)
        if best_m:
            m, a, b = best_m
            mn = _surname(names.get(m) or (drivers_i.get(m) or {}).get("name") or m)
            mine.append({"kind": "teammate", "score": 26 + 2 * abs(a - b),
                         "text": f"Ahead of team-mate {mn} at the finish in {a} of their {a + b} races together."})
        if rt:
            sc = 46 if rt["rank"] == 1 else max(FL.MIN_SCORE + 1, 34 - 2 * (rt["rank"] - 1))
            mine.append({"kind": "rating", "score": sc, "text": f"{sur} is {FL.ordinal(rt['rank'])} of {rt['of']} in our driver Elo ratings ({rt['text']})."})
        ctx = {"name": nm, "short": sur, "the": False, "phase": phase, "final": finished, "league_name": "F1 this season",
               "pctl": pctl_ctx(D, dmeta, D_PCTL, D_PROFILE, d) if d in D else [],
               "chances": [{"label": "Title", "series": series("drivers", d)}] if pt is not None and phase != "offseason" else []}
        fx = _select(mine, phase, ctx, asof)
        champion = {"event": "F1 drivers’", "season": y, "text": line} if finished and (meta.get("champion") == d or pos == 1) else None
        dcards[d] = FL.make_card(site=SITE, sport=SPORT, scope="driver", ident=d, team=team, asof=asof, phase=phase, season=y,
                                 now=now_blk, chances=chances, next_note=note, line=line, profile=profile_of(D, D_PROFILE, d) if d in D else None,
                                 facts=fx, champion=champion)
    # ── constructors
    tcards = {}
    for t in sorted(tst):
        ti = teams_i.get(t) or {}
        row = tst.get(t) or {}
        nm = ti.get("name") or t.replace("_", " ").title()
        short = re.sub(r" F1 Team| Racing| Formula One Team| Team$", "", nm).strip() or nm
        team = {"name": nm, "short": short, "abbr": short[:3].upper(), "colour": ti.get("colour"), "alt": ti.get("alt"), "href": f"#/team/{t}",
                "league": "F1", "group": "Constructors"}
        pts = _num(row.get("points"))
        pos = row.get("pos")
        st = {"pos": pos, "of": len(tst), "text": f"{FL.ordinal(pos)} in the constructors’ championship"} if pos else None
        rt = None
        if car.get(t) is not None and t in car_rank:
            rt = {"value": car[t], "text": _fmt(car[t], "3", "%"), "rank": car_rank[t], "of": len(car_rank), "label": "Car pace"}
        now_blk = {"record": f"{pts:.0f} pts" if pts is not None else None, "standing": st, "rating": rt}
        c = (champ.get("constructors") or {}).get(t) or {}
        pt = _num(c.get("p_title"))
        tdrv = [str(k) for k, r in dst.items() if r.get("team") == t]
        pwin = sum(_num(((fc.get("drivers") or {}).get(k) or {}).get("p_win")) or 0 for k in tdrv) if fc else None
        chances = []
        if phase != "offseason":
            if pwin is not None and pwin >= 0.005:
                chances.append({"key": "p_win", "label": f"{nshort} GP win", "p": round(pwin, 4), "d7": None})
            if pt is not None and (pt >= 0.005 or c.get("clinched")):
                chances.append({"key": "p_title", "label": "Constructors’ title", "p": _shown(pt, c), "d7": FL.change_since(series("constructors", t), asof, 7)})
        note = None
        if nxt and nstart and phase != "offseason":
            texp = _num(((fc.get("teams") or {}).get(t) or {}).get("exp_points")) if fc else None
            bits = ([f"Our chance of a win {FL.pct_text(pwin)}"] if (pwin or 0) >= 0.005 else []) + ([f"{texp:.0f} points expected"] if (texp or 0) >= 0.5 else [])
            note = f"Next: the {nxt.get('name')}, {_nice_day(nstart)}." + (" " + ", ".join(bits) + "." if bits else "")
        elif phase == "offseason":
            note = f"Season over. The {y + 1} season starts in March."
        line = f"{FL.ordinal(pos)} in the {y} constructors’ championship, {pts:.0f} points" + (f", {row.get('wins')} win{'s' if row.get('wins') != 1 else ''}" if row.get("wins") else "") + "." if pos and pts is not None else None
        players = []
        for k in sorted(tdrv, key=lambda k: -(_num(dst[k].get("points")) or 0))[:2]:
            r = dst[k]
            players.append({"name": names.get(k) or (drivers_i.get(k) or {}).get("name") or k, "pos": f"P{r.get('pos')}", "metric": "pts",
                            "value": _num(r.get("points")), "text": f"{(_num(r.get('points')) or 0):.0f}", "href": f"#/driver/{k}"})
        mine: list = []
        title_facts(short, True, "constructors", t, row, leader_t, second_t, "constructors’", mine)
        vs_last(short, True, "constructors", t, pts, mine)
        if players and pts:
            p0 = players[0]
            share = (p0["value"] or 0) / pts if pts else 0
            mine.append({"kind": "player_rank", "score": 24 + 30 * max(0.0, share - 0.5) + (12 if dst[tdrv[0]].get("pos") == 1 else 0) if tdrv else 24,
                         "text": f"{_surname(p0['name'])} has scored {p0['text']} of {_possessive(short)} {pts:.0f} points ({share * 100:.0f}%)."})
        if rt:
            sc = 48 if rt["rank"] == 1 else max(FL.MIN_SCORE + 1, 34 - 3 * (rt["rank"] - 1))
            word = "The fastest car on race pace in our model" if rt["rank"] == 1 else f"The {FL.ordinal(rt['rank'])}-fastest car on race pace in our model"
            mine.append({"kind": "rating", "score": sc, "text": f"{word}: {rt['text']} of a lap against the field."})
        ctx = {"name": nm, "short": short, "the": False, "phase": phase, "final": finished, "league_name": "F1 this season",
               "pctl": pctl_ctx(TC, tmeta, T_PCTL, T_PROFILE, t) if t in TC else [],
               "chances": [{"label": "Constructors’ title", "series": series("constructors", t)}] if pt is not None and phase != "offseason" else []}
        fx = _select(mine, phase, ctx, asof)
        champion = {"event": "F1 constructors’", "season": y, "text": line} if finished and (meta.get("constructors_champion") == t or pos == 1) else None
        tcards[t] = FL.make_card(site=SITE, sport=SPORT, scope="team", ident=t, team=team, asof=asof, phase=phase, season=y,
                                 now=now_blk, chances=chances, next_note=note, line=line, profile=profile_of(TC, T_PROFILE, t) if t in TC else None,
                                 facts=fx, players=players, champion=champion)
    out = out_dir or (data / "follow")
    return {"driver": FL.write_cards(out, "driver", dcards), "team": FL.write_cards(out, "team", tcards)}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Write the Paddock's follow cards from the payloads on disk")
    ap.add_argument("--data", default="docs/paddock/data")
    ap.add_argument("--now", default=None, help="ISO build clock (default now)")
    a = ap.parse_args(argv)
    s = build(Path(a.data), FL._dt(a.now) if a.now else None)
    for k, v in s.items():
        print(f"{k}: {v['n']} cards, {v['bytes'] / 1024:.0f} KB, largest {v['max']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
