"""The Rink's follow cards (My Teams): one small card per club at data/follow/team/<ABBR>.json.

The schema and the fact engine are oddsmarkets/common/follow.py; this module only gathers what the Rink build has
already written this run (no new fetching):

    index.json                 the clubs (names, colours, divisions), the phase
    <S>/season.json            standings (record, points, streak, place, clinch codes), the simulation (division,
                               Presidents' Trophy, Cup), the league block (luck, the schedule left)
    <S>/teams.json             each club's schedule (results with the frozen pre-game chance, the games to come with
                               ours and the market's), its team stats (units: the profile percentiles are computed here,
                               with oddsmarkets/common/league.py profile() on the race spec), its goalies
    <S>/schedule.json          start times (teams.json schedule rows carry the date only)
    <S>/skaters.json, goalies.json   the top players: GAR per 60 for skaters, GSAx for goalies, ranked in the league
    <S-1>/season.json, teams.json    last season's records, and "at this point last season"
    race_log.json              our playoff, division and Cup chances by day (the 7-day change)
    <S>/rating_history.json    the team rating's league rank going into each week (rating_history.py): the
                               "rating move" fact, against the published rating's rank today
    history.json               the Cup winner of a finished season

    build(data_root, now=None) -> {"n", "bytes", "max", "ids"}        (python -m oddsmarkets.nhl.analytics.follow_build)

No look-ahead: a result counts only once its date is at or before the build clock, a finished game's chance is the
model's pre-game number, and the 7-day change compares two race-log snapshots taken on those days.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL
from oddsmarkets.common import league as LG

log = logging.getLogger(__name__)

SITE, SPORT, SCOPE = "rink", "hockey", "team"
PHASE = {"preseason": "preseason", "regular": "season", "playoffs": "postseason", "postseason": "postseason",
         "offseason": "offseason", "complete": "offseason"}
LEAGUE = "NHL"
# the card's headline chance is the last one listed (QK.followCard): the playoff chance, in season
CHANCES = (("p_cup", "Stanley Cup"), ("p_playoffs", "Playoff"))
BIG_GAME = 60                   # the significance score a next game needs for its own "big one next" fact
MIN_TOI_SKATER = 100.0          # minutes: GAR per 60 over a handful of shifts is noise
MIN_GP_GOALIE = 3


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
    if f in ("+2", "+1"):
        d = 2 if f == "+2" else 1
        return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v):.{d}f}"
    m = "−" if v < 0 else ""
    a = abs(v)
    if f == "pct1":
        return m + f"{a * 100:.1f}%"
    if f == "pct0":
        return m + f"{a * 100:.0f}%"
    if f == "3":
        return m + (f"{a:.3f}".replace("0.", ".", 1) if a < 1 else f"{a:.3f}")
    if f == "2":
        return m + f"{a:.2f}"
    if f == "1":
        return m + f"{a:.1f}"
    return m + f"{a:g}"


def _label(season: int) -> str:
    """20252026 -> '2025-26'."""
    s = str(season)
    return f"{s[:4]}-{s[6:]}" if len(s) == 8 else s


def _ties(rank: dict) -> set:
    seen: dict = {}
    for k, r in rank.items():
        seen.setdefault(r, []).append(k)
    return {k for ks in seen.values() if len(ks) > 1 for k in ks}


def _res_letter(r) -> str | None:
    r = str(r or "").upper()
    return "W" if r == "W" else "O" if r in ("OTL", "SOL", "OT") else "L" if r == "L" else None


def results_of(sched: list[dict], starts: dict, asof: datetime) -> list[dict]:
    """A club's finished games at `asof`, oldest first, as follow.py results: {"start", "res" (W, L, or O for an
    overtime or shootout loss), "p", "us", "them", "home", "opp", "id"}."""
    out = []
    for g in sched or []:
        res = _res_letter(g.get("result"))
        if g.get("status") != "final" or res is None or _num(g.get("gf")) is None or _num(g.get("ga")) is None:
            continue
        st = starts.get(str(g.get("game_id"))) or g.get("date")
        t = FL._dt(st)
        if t is None or t > asof:
            continue
        out.append({"start": str(st), "res": res, "p": _num(g.get("p_win")), "us": int(g["gf"]), "them": int(g["ga"]),
                    "home": bool(g.get("home")), "opp": str(g.get("opp")), "id": str(g.get("game_id"))})
    out.sort(key=lambda r: r["start"])
    return out


def upcoming_of(sched: list[dict], starts: dict, asof: datetime, n: int = 3) -> list[dict]:
    """The next n games not started at `asof` (with their start, where schedule.json has it)."""
    out = []
    for g in sched or []:
        if g.get("status") in ("final", "live", "postponed", "cancelled") or g.get("result"):
            continue
        st = starts.get(str(g.get("game_id")))
        t = FL._dt(st) if st else FL._dt(g.get("date"))
        if t is None:
            continue
        if st and t <= asof:
            continue
        if not st and t.date() < asof.date():
            continue
        out.append((t, dict(g, _start=st)))
    out.sort(key=lambda x: x[0])
    return [g for _, g in out[:n]]


def _record_after(sched: list[dict], n: int) -> tuple | None:
    """(w, l, otl) after a club's first n finished games of a season (None when it played fewer)."""
    rs = [_res_letter(g.get("result")) for g in sorted((g for g in sched or [] if g.get("status") == "final"), key=lambda g: str(g.get("date")))]
    rs = [r for r in rs if r]
    if len(rs) < n or n <= 0:
        return None
    rs = rs[:n]
    return rs.count("W"), rs.count("L"), rs.count("O")


def _rec(w, l, otl) -> str | None:
    if _num(w) is None or _num(l) is None:
        return None
    return FL.DASH.join(str(int(x)) for x in (w, l, otl or 0))


def _short(name: str | None) -> str:
    """'Toronto Maple Leafs' -> 'Maple Leafs', 'Utah Mammoth' -> 'Mammoth', the two-word city names kept apart."""
    nm = str(name or "")
    two = ("Maple Leafs", "Blue Jackets", "Red Wings", "Golden Knights")
    for x in two:
        if nm.endswith(" " + x):
            return x
    return nm.split(" ")[-1] if " " in nm else nm


def _rivalry(a: str | None, b: str | None) -> str | None:
    from oddsmarkets.common import featured as FT
    if not a or not b:
        return None
    for pair, name in FT.RIVALRIES.items():
        x, y = tuple(pair)
        if (a.endswith(x) and b.endswith(y)) or (a.endswith(y) and b.endswith(x)):
            return name
    return None


def _clinch_text(code) -> dict | None:
    c = str(code or "").lower()
    if not c:
        return None
    if c in ("e",):
        return {"eliminated": "the playoff race"}
    if c in ("p",):
        return {"clinched": "the Presidents' Trophy"}
    if c in ("z",):
        return {"clinched": "the conference"}
    if c in ("y",):
        return {"clinched": "the division"}
    if c in ("x",):
        return {"clinched": "a playoff place"}
    return None


def _players(team: str, sk: dict, gk: dict) -> tuple[list[dict], list[dict]]:
    """The club's top two by the Rink's value metric: skaters by GAR per 60 (from MIN_TOI_SKATER minutes), goalies by
    GSAx, each ranked in the league among its kind; the two with the best league rank go on the card."""
    sks = []
    for pid, p in (sk or {}).items():
        v = _num((p.get("values") or {}).get("gar_60"))
        if v is None or (_num(p.get("toi")) or 0) < MIN_TOI_SKATER:
            continue
        sks.append((v, pid, p))
    gks = []
    for pid, p in (gk or {}).items():
        v = _num((p.get("values") or {}).get("gsax"))
        if v is None or (_num(p.get("gp")) or 0) < MIN_GP_GOALIE:
            continue
        gks.append((v, pid, p))
    out = []
    for pool, kind in ((sks, "skater"), (gks, "goalie")):
        vals = [v for v, _, _ in pool]
        for v, pid, p in pool:
            if str(p.get("team")) != team:
                continue
            rk = 1 + sum(1 for x in vals if x > v)
            tied = sum(1 for x in vals if x == v) > 1
            out.append({"pid": pid, "name": p.get("name"), "pos": p.get("pos"), "kind": kind, "v": v, "rank": rk, "of": len(vals), "tied": tied})
    out.sort(key=lambda x: (x["rank"] / max(1, x["of"]), -x["v"]))
    top = out[:2]
    card = []
    for x in top:
        if x["kind"] == "goalie":
            card.append({"name": x["name"], "pos": "G", "metric": "GSAx", "value": round(x["v"], 1), "text": _fmt(x["v"], "+1"), "href": f"#/player/{x['pid']}"})
        else:
            card.append({"name": x["name"], "pos": x["pos"], "metric": "GAR/60", "value": round(x["v"], 2), "text": _fmt(x["v"], "+2"), "href": f"#/player/{x['pid']}"})
    return card, top


def build(data: Path, now: datetime | None = None, out_dir: Path | None = None) -> dict:
    """Write data/follow/team/<ABBR>.json for every club of the current season; returns write_cards' summary."""
    data = Path(data)
    asof = now or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=timezone.utc)
    idx = _read(data / "index.json") or {}
    season = idx.get("season")
    if not season:
        raise ValueError("no current season in index.json")
    season = int(season)
    sdir = data / str(season)
    sj = _read(sdir / "season.json") or {}
    tj = (_read(sdir / "teams.json") or {}).get("teams") or {}
    starts = {str(g.get("game_id")): g.get("start") for g in ((_read(sdir / "schedule.json") or {}).get("games") or []) if g.get("start")}
    raw_phase = str(sj.get("phase") or idx.get("phase") or "regular")
    phase = PHASE.get(raw_phase, "season")
    final = phase == "offseason"
    info = dict(idx.get("teams") or {})
    for t, x in tj.items():
        info.setdefault(t, {k: x.get(k) for k in ("name", "colour", "alt", "division", "conference")})
    st = sj.get("standings") or {}
    rows = {str(r.get("team")): r for r in st.get("rows") or []}
    teams = sorted(t for t in info if t in rows or t in tj)
    if not teams:
        raise ValueError(f"no clubs for {season}")
    # the place in the division (the standings' own order), and the league order by points %
    place = {}
    for d in st.get("divisions") or []:
        for i, t in enumerate(d.get("teams") or [], 1):
            place[str(t)] = (i, len(d.get("teams") or []), d.get("division"))
    sim = ((sj.get("sim") or {}).get("teams") or {}) if (sj.get("sim") or {}).get("ok") else {}
    odds = idx.get("playoff_odds") or {}
    rating = {t: _num(((tj.get(t) or {}).get("units") or {}).get("rating")) if _num(((tj.get(t) or {}).get("units") or {}).get("rating")) is not None
              else _num((rows.get(t) or {}).get("rating")) for t in teams}
    rating_rank = LG.ranks(rating)
    n_rated = len([v for v in rating.values() if v is not None])
    pct_rank = LG.ranks({t: _num((rows.get(t) or {}).get("p_pct")) for t in teams if (rows.get(t) or {}).get("gp")})
    # the profile: league percentiles on the race spec, computed here from teams.json's team stats
    from oddsmarkets.nhl.analytics import race as RC
    L = sj.get("league") or {}
    spec_lab = {m["id"]: m for m in (L.get("profile") or {}).get("metrics") or []}
    spec = [dict(m, **{k: v for k, v in (spec_lab.get(m["id"]) or {}).items() if k in ("label", "fmt", "unit")}) for m in RC.SPEC]
    vals, gp = {}, {}
    for t in teams:
        u = (tj.get(t) or {}).get("units") or {}
        r = rows.get(t) or {}
        v = {m["id"]: _num(u.get(m["id"])) for m in spec}
        if v.get("rating") is None:
            v["rating"] = rating.get(t)
        if v.get("gd_g") is None and r.get("gp"):
            v["gd_g"] = ((r.get("gf") or 0) - (r.get("ga") or 0)) / r["gp"]
        vals[t] = v
        gp[t] = int(r.get("gp") or 0)
    prof_all = LG.profile(vals, spec, gp, RC.MIN_GP)
    rank_ties = {}
    for m in spec:
        col = {t: (prof_all.get(t) or {}).get("rank", {}).get(m["id"]) for t in teams}
        rank_ties[m["id"]] = _ties({t: r for t, r in col.items() if r is not None})
    lteams = L.get("teams") or {}
    race = L.get("race") or {}
    notes = L.get("notes") or {}
    rlog = (_read(data / "race_log.json") or {}).get(str(season)) or {}
    # the weekly rating ranks (each Monday's refit on the games before it), then today's published rank
    rh = _read(sdir / "rating_history.json") or {}
    rank_hist = {t: [] for t in teams}
    if rh.get("ok") and int(rh.get("season") or 0) == season:
        wk = list(rh.get("weeks") or [])
        for t in teams:
            rank_hist[t] = [[w, r] for w, r in zip(wk, (rh.get("ranks") or {}).get(t) or []) if r is not None and FL._dt(w) is not None and FL._dt(w) <= asof]
    for t in teams:
        if rating_rank.get(t) is not None:
            rank_hist[t].append([asof.isoformat(), rating_rank[t]])
    # last season: records, and "at this point" from its schedule (read only when needed)
    prev_s = season - 10001                                         # NHL season ids: 20252026 before 20262027
    prev_rows = {str(r.get("team")): r for r in (((_read(data / str(prev_s) / "season.json") or {}).get("standings") or {}).get("rows") or [])}
    prev_tj = None
    # the champion of a finished season (history.json)
    champ_row = None
    if final:
        for c in (_read(data / "history.json") or {}).get("champions") or []:
            if int(c.get("season") or 0) == season and c.get("champion"):
                champ_row = c
    # home and road records across the league (points %), for the split fact
    res = {t: results_of((tj.get(t) or {}).get("schedule") or [], starts, asof) for t in teams}
    split = {}
    for t in teams:
        hs = [r for r in res[t] if r["home"]]
        aw = [r for r in res[t] if not r["home"]]
        split[t] = {side: (sum(1 for r in rs if r["res"] == "W"), sum(1 for r in rs if r["res"] == "L"), sum(1 for r in rs if r["res"] == "O")) for side, rs in (("home", hs), ("away", aw))}
    ppct = lambda x: (2 * x[0] + x[2]) / (2 * max(1, sum(x)))                  # noqa: E731
    # a split rank counts only once two thirds of the league has played that many games on that side
    home_rank = LG.ranks({t: ppct(v["home"]) for t, v in split.items() if sum(v["home"]) >= 8})
    away_rank = LG.ranks({t: ppct(v["away"]) for t, v in split.items() if sum(v["away"]) >= 8})
    home_rank = home_rank if len(home_rank) >= 2 * len(teams) / 3 else {}
    away_rank = away_rank if len(away_rank) >= 2 * len(teams) / 3 else {}
    sk = (_read(sdir / "skaters.json") or {}).get("players") or {}
    gk = (_read(sdir / "goalies.json") or {}).get("players") or {}
    from oddsmarkets.common import featured as FT
    cards = {}
    for t in teams:
        ti = info.get(t) or {}
        r = rows.get(t) or {}
        name = ti.get("name") or t
        short = _short(name)
        pos, of, div = place.get(t, (None, None, ti.get("division")))
        team = {"name": name, "short": short, "abbr": t, "colour": ti.get("colour"), "alt": ti.get("alt"), "href": f"#/team/{t}",
                "league": LEAGUE, "group": div}
        rec = _rec(r.get("w"), r.get("l"), r.get("otl"))
        stand = None
        if pos:
            stand = {"pos": pos, "of": of, "group": div, "text": f"{FL.ordinal(pos)} in the {div}" + (f", {int(r['pts'])} points" if _num(r.get("pts")) is not None else "")}
        rt = None
        if rating.get(t) is not None:
            rt = {"value": rating[t], "text": _fmt(rating[t], "+2"), "rank": rating_rank.get(t), "of": n_rated, "label": "Team rating"}
        now_blk = {"record": rec, "form": None if final else FL.form_letters(res[t], asof), "streak": None, "standing": stand, "rating": rt}
        sk_ = FL.streak_of(res[t], asof)
        if sk_ and not final:
            now_blk["streak"] = f"{sk_[0]}{sk_[1]}"
        # chances with the 7-day change from the race log
        chances, ctx_ch = [], []
        if not final:
            so = sim.get(t) or {}
            for key, lab in CHANCES:
                p = _num(so.get(key)) if _num(so.get(key)) is not None else _num((odds.get(t) or {}).get(key))
                if p is None:
                    p = _num(r.get(key))
                if p is None:
                    continue
                ser = {d: (v or {}).get(t) for d, v in (rlog.get(key) or {}).items() if isinstance(v, dict)}
                chances.append({"key": key, "label": lab, "p": round(p, 4), "d7": FL.change_since(ser, asof, 7)})
                ctx_ch.append({"label": lab, "series": ser})
        # the next games, from teams.json (our chance, the market's), start times from schedule.json
        nxt = []
        for g in (upcoming_of((tj.get(t) or {}).get("schedule") or [], starts, asof) if not final else []):
            o = str(g.get("opp"))
            oi = info.get(o) or {}
            home = bool(g.get("home"))
            h, a = (t, o) if home else (o, t)
            sig = {"playoff": [_num((odds.get(h) or {}).get("p_playoffs")), _num((odds.get(a) or {}).get("p_playoffs"))],
                   "title": [_num((odds.get(h) or {}).get("p_cup")), _num((odds.get(a) or {}).get("p_cup"))]}
            rv = _rivalry(name, oi.get("name"))
            if rv:
                sig["rivalry"] = rv
            pw = _num(g.get("p_win"))
            fg = {"sport": SPORT, "league": LEAGUE, "id": g.get("game_id"), "start": g.get("_start") or g.get("date"), "status": "pre",
                  "p_home": (pw if home else (1 - pw)) if pw is not None else None, "sig": sig}
            sg = FT.significance(fg, asof)
            nxt.append({"id": str(g.get("game_id")), "start": g.get("_start") or g.get("date"), "tba": None if g.get("_start") else True, "home": home,
                        "opp": {"name": _short(oi.get("name") or o), "abbr": o, "colour": oi.get("colour"), "rank": rating_rank.get(o)},
                        "comp": LEAGUE, "p": pw, "mkt": _num(g.get("p_market")), "why": sg["reasons"][:2], "href": f"#/game/{g.get('game_id')}",
                        "_score": sg["score"], "_reasons": sg["reasons"], "_rv": rv, "_short": _short(oi.get("name") or o)})
        note = None
        if not nxt:
            note = (f"Season over. The {_label(season + 10001)} schedule is not out yet." if final else
                    "The schedule is not out yet." if phase == "preseason" else "No games in the next few days.")
        last = None
        if res[t]:
            x = res[t][-1]
            oi = info.get(x["opp"]) or {}
            last = {"id": x["id"], "start": x["start"], "home": x["home"], "opp": {"name": _short(oi.get("name") or x["opp"]), "abbr": x["opp"], "colour": oi.get("colour")},
                    "score": [x["us"], x["them"]], "res": "L" if x["res"] == "O" else x["res"], "p": x["p"], "upset": FL.upset_flag(x["p"], x["res"]),
                    "comp": LEAGUE + (" · OT/SO" if x["res"] == "O" else ""), "href": f"#/game/{x['id']}"}
        # the profile: the 3 strongest and 2 weakest of the team metrics, as league percentiles
        pa = prof_all.get(t) or {}
        pc = pa.get("pct") or {}
        prow = [{"id": m["id"], "label": m.get("label") or m["id"], "pct": int(pc[m["id"]]), "text": _fmt(vals[t].get(m["id"]), m.get("fmt"))}
                for m in spec if pc.get(m["id"]) is not None]
        prow.sort(key=lambda x: -x["pct"])
        profile = {"strong": prow[:3], "weak": sorted(prow[3:], key=lambda x: x["pct"])[:2]} if len(prow) >= 5 else None
        players, top = _players(t, sk, gk)
        # ── the facts
        ctx = {"name": name, "short": short, "the": True, "phase": phase, "final": final, "league_name": "the NHL", "results": res[t],
               "rating_ranks": rank_hist.get(t) or []}
        pr = []
        for m in spec:
            if m["id"] == "rating":
                continue                                           # the rating has its own fact
            rk = (pa.get("rank") or {}).get(m["id"])
            if rk:
                pr.append({"label": m.get("label") or m["id"], "rank": rk, "of": len([x for x in teams if (prof_all.get(x) or {}).get("rank", {}).get(m["id"])]),
                           "tied": t in rank_ties.get(m["id"], set()), "text": _fmt(vals[t].get(m["id"]), m.get("fmt")), "model": bool(m.get("model"))})
        ctx["pctl"] = pr
        if pct_rank.get(t) in (1, 2) and rec:
            ctx["best_record"] = {"record": f"{rec}, {int(r.get('pts') or 0)} points", "scope": "league", "where": "the NHL", "rank": pct_rank[t]}
        elif pos == 1 and rec and div:
            ctx["best_record"] = {"record": f"{rec}, {int(r.get('pts') or 0)} points", "scope": "group", "where": f"{div} Division"}
        sp = split.get(t) or {}
        ctx["split"] = {"of": max(len(home_rank), len(away_rank)), "league": "the NHL",
                        "home": {"record": _rec(*sp.get("home", (None, None, None))), "rank": home_rank.get(t), "tied": t in _ties(home_rank)},
                        "away": {"record": _rec(*sp.get("away", (None, None, None))), "rank": away_rank.get(t), "tied": t in _ties(away_rank)}}
        lk = (lteams.get(t) or {}).get("luck") or {}
        if _num(lk.get("d")) is not None:
            ctx["luck"] = {"d": lk["d"], "unit": "wins", "basis": "their expected goals for and against deserved"}
        rc = race.get(t) or {}
        if rc.get("sos") and phase == "season" and rc["sos"][1]:
            avg, rk, left = rc["sos"]
            ctx["sos"] = {"rank": rk, "of": len(teams), "left": left, "where": "the NHL", "text": f"{_fmt(avg, '+2')} goals a game"}
        cl = _clinch_text(r.get("clinch"))
        if cl:
            ctx["clinch"] = cl
        elif rc.get("magic") and phase == "season":
            ctx["clinch"] = {"magic": rc["magic"], "what": "a playoff place"}
        ctx["chances"] = ctx_ch
        if nxt:
            g0 = nxt[0]
            ctx["next"] = {"start": g0["start"], "opp": {"short": g0["_short"], "name": g0["opp"]["name"]}, "p": g0["p"],
                           "score": g0["_score"] if g0["_score"] >= BIG_GAME else None, "reasons": g0["_reasons"], "rivalry": g0["_rv"]}
        if top:
            p0 = top[0]
            if p0["kind"] == "goalie":
                ctx["players"] = [{"name": p0["name"], "text": _fmt(p0["v"], "+1"), "metric": "goals saved above expected", "rank": p0["rank"], "of": p0["of"],
                                   "tied": p0["tied"], "pool": "NHL goalies"}]
            else:
                ctx["players"] = [{"name": p0["name"], "text": _fmt(p0["v"], "+2"), "metric": "GAR per 60", "rank": p0["rank"], "of": p0["of"],
                                   "tied": p0["tied"], "pool": "NHL skaters (100+ minutes)"}]
        pv = prev_rows.get(t)
        if pv and _num(pv.get("w")) is not None and _num(r.get("w")) is not None:
            if final:
                ctx["vs_last"] = {"now": [int(r["w"]), int(r["l"]), int(r.get("otl") or 0)], "last": [int(pv["w"]), int(pv["l"]), int(pv.get("otl") or 0)],
                                  "season_last": _label(prev_s), "full": True}
            elif int(r.get("gp") or 0) >= 10:
                if prev_tj is None:
                    prev_tj = (_read(data / str(prev_s) / "teams.json") or {}).get("teams") or {}
                at = _record_after((prev_tj.get(t) or {}).get("schedule") or [], int(r["gp"]))
                if at:
                    ctx["vs_last"] = {"now": [int(r["w"]), int(r["l"]), int(r.get("otl") or 0)], "last": list(at),
                                      "season_last": _label(prev_s)}
        champ = None
        if champ_row and champ_row.get("champion") == name:
            ctx["champion"] = {"event": "Stanley Cup", "season": champ_row.get("label") or season, "opp": _short(champ_row.get("finalist"))}
            champ = {"event": "Stanley Cup", "season": champ_row.get("label") or season, "text": f"Won the {champ_row.get('label')} Stanley Cup over the {_short(champ_row.get('finalist'))}."}
        if rt:
            ctx["rating"] = {"rank": rt["rank"], "of": rt["of"], "text": rt["text"], "unit": "goals a game"}
        fx = FL.facts(ctx, asof)
        for g in nxt:
            for k in ("_score", "_reasons", "_rv", "_short"):
                g.pop(k, None)
        line = None
        if champ:
            line = champ["text"]
        elif rec:
            line = (f"Season over: {rec}" if final else rec) + (f", {stand['text']}" if stand else "") + "."
        cards[t] = FL.make_card(site=SITE, sport=SPORT, scope=SCOPE, ident=t, team=team, asof=asof, phase=phase, season=season,
                                now=now_blk, chances=chances, next_games=nxt, next_note=note, last=last, line=line, profile=profile,
                                facts=fx, players=players, champion=champ)
    return FL.write_cards(out_dir or (data / "follow"), SCOPE, cards)


def main(argv=None) -> int:
    import argparse
    from oddsmarkets.nhl import analytics as an
    ap = argparse.ArgumentParser(description="Write the Rink's follow cards from the payloads on disk")
    ap.add_argument("--data", default=None)
    ap.add_argument("--now", default=None, help="ISO build clock (default now)")
    a = ap.parse_args(argv)
    data = Path(a.data) if a.data else an.data_root()
    s = build(data, FL._dt(a.now) if a.now else None)
    print(f"team: {s['n']} cards, {s['bytes'] / 1024:.0f} KB, largest {s['max']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
