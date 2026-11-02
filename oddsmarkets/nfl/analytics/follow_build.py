"""The Gridiron's follow cards (My Teams): one small card per team at data/follow/team/<ABBR>.json.

The schema and the fact engine are oddsmarkets/common/follow.py; this module only gathers what the Gridiron build has
already written this run (no new fetching):

    index.json                 the teams (names, colours, divisions), the phase, the week
    <S>/season.json            standings (record, home and road, streak, the simulation's chances, magic numbers,
                               clinches), the league block (luck, the schedule left, the profile spec)
    <S>/teams.json             short names, the team metrics with their league percentiles (pct), the weekly rating
                               history (the rating move), every game with our pre-game chance
    <S>/schedule.json          the market's chance on the games to come (a quiet reference beside ours)
    <S>/value.json             the top players: Gridiron Value per game, ranked at the player's position
    <S-1>/season.json, teams.json    last season's records, and "at this point last season"
    race_log.json              our playoff, division and Super Bowl chances by day (the 7-day change)
    history.json               the Super Bowl winner of a finished season

    build(data_root, now=None) -> {"n", "bytes", "max", "ids"}        (python -m oddsmarkets.nfl.analytics.follow_build)

No look-ahead: a result counts only once its kickoff is at or before the build clock, a finished game's chance is the
model's pre-game number (walk-forward or frozen before kickoff), a week's rating is dated at that week's first
kickoff (it is the rating going into the week), and the 7-day change compares two race-log snapshots taken on those
days.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL
from oddsmarkets.common import league as LG

log = logging.getLogger(__name__)

SITE, SPORT, SCOPE = "gridiron", "nfl", "team"
PHASE = {"preseason": "preseason", "regular": "season", "postseason": "postseason", "playoffs": "postseason",
         "offseason": "offseason", "complete": "offseason"}
LEAGUE = "NFL"
# the card's headline chance is the last one listed (QK.followCard): the playoff chance, in season
CHANCES = (("p_sb", "Super Bowl", "Super Bowl"), ("p_div", "Division", "Division"), ("p_playoffs", "Playoff", "Playoff"))
BIG_GAME = 60                  # the significance score a next game needs for its own "big one next" fact
MAGIC_MAX = 3                  # a magic number is a fact only within reach (11 wins in October says nothing)
POS_PLURAL = {"QB": "quarterbacks", "RB": "running backs", "WR": "wide receivers", "TE": "tight ends", "EDGE": "edge rushers",
              "DL": "interior linemen", "LB": "linebackers", "CB": "cornerbacks", "S": "safeties", "K": "kickers", "P": "punters"}
POST_NAME = {"WC": "Wild Card round", "DIV": "Divisional round", "CON": "Conference championship", "SB": "Super Bowl"}


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
    if f == "2":
        return m + f"{a:.2f}"
    if f == "1":
        return m + f"{a:.1f}"
    return m + f"{a:g}"


def _ties(rank: dict) -> set:
    seen: dict = {}
    for k, r in rank.items():
        seen.setdefault(r, []).append(k)
    return {k for ks in seen.values() if len(ks) > 1 for k in ks}


def _rec(w, l, t=None) -> str | None:
    return FL.record_text(w, l, t)


def _side_p(g: dict, team: str) -> float | None:
    p = _num((g.get("model") or {}).get("p_home"))
    if p is None:
        return None
    return round(p if g.get("home") == team else 1 - p, 4)


def results_of(sched: list[dict], team: str, asof: datetime) -> list[dict]:
    """A team's finished games at `asof`, oldest first, as follow.py results: {"start", "res" (W, L, D), "p", "us",
    "them", "home", "opp", "id", "gtype", "week"}."""
    out = []
    for g in sched or []:
        if g.get("status") != "final" or _num(g.get("hs")) is None or _num(g.get("as")) is None:
            continue
        t = FL._dt(g.get("kickoff"))
        if t is None or t > asof:
            continue
        home = g.get("home") == team
        us, them = (g["hs"], g["as"]) if home else (g["as"], g["hs"])
        out.append({"start": g["kickoff"], "res": "W" if us > them else "L" if us < them else "D", "p": _side_p(g, team), "us": int(us),
                    "them": int(them), "home": home, "opp": g.get("away") if home else g.get("home"), "id": str(g.get("game_id")),
                    "gtype": g.get("gtype"), "week": g.get("week")})
    out.sort(key=lambda r: r["start"])
    return out


def upcoming_of(sched: list[dict], asof: datetime, n: int = 3) -> list[dict]:
    out = []
    for g in sched or []:
        if g.get("status") in ("final", "live", "postponed", "cancelled"):
            continue
        t = FL._dt(g.get("kickoff"))
        if t is None or t <= asof:
            continue
        out.append((t, g))
    out.sort(key=lambda x: x[0])
    return [g for _, g in out[:n]]


def _record_after(sched: list[dict], team: str, n: int) -> tuple | None:
    rs = []
    for g in sorted((g for g in sched or [] if g.get("status") == "final" and g.get("gtype", "REG") == "REG"), key=lambda g: str(g.get("kickoff"))):
        if _num(g.get("hs")) is None or _num(g.get("as")) is None:
            continue
        home = g.get("home") == team
        us, them = (g["hs"], g["as"]) if home else (g["as"], g["hs"])
        rs.append("W" if us > them else "L" if us < them else "D")
    if len(rs) < n or n <= 0:
        return None
    rs = rs[:n]
    return rs.count("W"), rs.count("L"), rs.count("D")


def _rivalry(a: str | None, b: str | None) -> str | None:
    from oddsmarkets.common import featured as FT
    if not a or not b:
        return None
    for pair, name in FT.RIVALRIES.items():
        x, y = tuple(pair)
        if (a.endswith(" " + x) and b.endswith(" " + y)) or (a.endswith(" " + y) and b.endswith(" " + x)):
            return name
    return None


def _players(team: str, val: dict) -> tuple[list[dict], dict | None]:
    """The team's top two by Gridiron Value per game (qualified players), each ranked at its position."""
    cols = val.get("cols") or []
    if not cols:
        return [], None
    at = {c: i for i, c in enumerate(cols)}
    need = ("pid", "name", "team", "pos", "gvar_pg")
    if any(c not in at for c in need):
        return [], None
    rows = [r for r in val.get("rows") or [] if _num(r[at["gvar_pg"]]) is not None and (("q" not in at) or r[at["q"]])]
    by_pos: dict = {}
    for r in rows:
        by_pos.setdefault(r[at["pos"]], []).append(float(r[at["gvar_pg"]]))
    mine = sorted((r for r in rows if r[at["team"]] == team), key=lambda r: -float(r[at["gvar_pg"]]))[:2]
    card = [{"name": r[at["name"]], "pos": r[at["pos"]], "metric": "value/game", "value": round(float(r[at["gvar_pg"]]), 2),
             "text": _fmt(r[at["gvar_pg"]], "+2"), "href": f"#/player/{r[at['pid']]}"} for r in mine]
    top = None
    if mine:
        r = mine[0]
        v, pool = float(r[at["gvar_pg"]]), by_pos.get(r[at["pos"]]) or []
        top = {"name": r[at["name"]], "text": _fmt(v, "+2"), "metric": "value a game", "rank": 1 + sum(1 for x in pool if x > v), "of": len(pool),
               "tied": sum(1 for x in pool if x == v) > 1, "pool": "NFL " + POS_PLURAL.get(r[at["pos"]], r[at["pos"]].lower() + "s")}
    return card, top


def _week_starts(games: list[dict]) -> dict:
    """{week: the first kickoff of that regular-season week}."""
    out: dict = {}
    for g in games or []:
        w, k = g.get("week"), g.get("kickoff")
        if g.get("gtype", "REG") != "REG" or w is None or not k:
            continue
        if w not in out or str(k) < out[w]:
            out[w] = str(k)
    return out


def build(data: Path, now: datetime | None = None, out_dir: Path | None = None) -> dict:
    """Write data/follow/team/<ABBR>.json for every team of the current season; returns write_cards' summary."""
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
    tjp = _read(sdir / "teams.json") or {}
    tj = tjp.get("teams") or {}
    games = (_read(sdir / "schedule.json") or {}).get("games") or []
    by_id = {str(g.get("game_id")): g for g in games}
    raw_phase = str(sj.get("phase") or idx.get("phase") or "regular")
    phase = PHASE.get(raw_phase, "season")
    final = phase == "offseason"
    info = dict(idx.get("teams") or {})
    for t, x in tj.items():
        info.setdefault(t, {k: x.get(k) for k in ("name", "colour", "alt", "division", "conference")})
        if x.get("short"):
            info[t] = dict(info[t], short=x["short"])
    rows, place = {}, {}
    for d in sj.get("standings") or []:
        rs = list(d.get("teams") or [])
        rs.sort(key=lambda r: -(_num(r.get("pct")) or 0))
        lead = rs[0] if rs else {}
        for i, r in enumerate(rs, 1):
            t = str(r.get("team"))
            rows[t] = r
            gb = ((int(lead.get("w") or 0) - int(r.get("w") or 0)) + (int(r.get("l") or 0) - int(lead.get("l") or 0))) / 2 if lead else None
            place[t] = (i, len(rs), d.get("division"), gb)
    teams = sorted(t for t in info if t in rows or t in tj)
    if not teams:
        raise ValueError(f"no teams for {season}")
    sim = ((sj.get("sim") or {}).get("teams") or {}) if (sj.get("sim") or {}).get("ok") else {}
    odds = idx.get("playoff_odds") or {}
    rating = {t: _num(((tj.get(t) or {}).get("values") or {}).get("rating")) if _num(((tj.get(t) or {}).get("values") or {}).get("rating")) is not None
              else _num((rows.get(t) or {}).get("rating")) for t in teams}
    rating_rank = LG.ranks(rating)
    n_rated = len([v for v in rating.values() if v is not None])
    pct_rank = LG.ranks({t: _num((rows.get(t) or {}).get("pct")) for t in teams if (rows.get(t) or {}).get("w") is not None and
                         (int(rows[t].get("w") or 0) + int(rows[t].get("l") or 0) + int(rows[t].get("t") or 0)) > 0})
    # the profile: teams.json's league percentiles (pct), on the league block's spec (labels, formats, direction)
    L = sj.get("league") or {}
    spec = [m for m in (L.get("profile") or {}).get("metrics") or [] if not m.get("style")]
    lteams = L.get("teams") or {}
    vals = {t: {m["id"]: (_num(((tj.get(t) or {}).get("values") or {}).get(m["id"])) if _num(((tj.get(t) or {}).get("values") or {}).get(m["id"])) is not None
                          else _num(((lteams.get(t) or {}).get("vals") or {}).get(m["id"]))) for m in spec} for t in teams}
    pcts = {t: {m["id"]: (_num(((tj.get(t) or {}).get("pct") or {}).get(m["id"])) if _num(((tj.get(t) or {}).get("pct") or {}).get(m["id"])) is not None
                          else _num(((lteams.get(t) or {}).get("pct") or {}).get(m["id"]))) for m in spec} for t in teams}
    ranks, ties = {}, {}
    for m in spec:
        rk = LG.ranks({t: vals[t][m["id"]] for t in teams}, high_first=m.get("dir", "higher") != "lower")
        ranks[m["id"]], ties[m["id"]] = rk, _ties(rk)
    race = L.get("race") or {}
    rlog = (_read(data / "race_log.json") or {}).get(str(season)) or {}
    # our weekly ratings, as league ranks dated at each week's first kickoff (the rating going into that week)
    wk_start = _week_starts(games)
    by_week: dict = {}
    for t in teams:
        for h in (tj.get(t) or {}).get("history") or []:
            if isinstance(h, list) and len(h) >= 2 and _num(h[1]) is not None:
                by_week.setdefault(int(h[0]), {})[t] = float(h[1])
    rank_hist = {t: [] for t in teams}
    for w, col in sorted(by_week.items()):
        if w not in wk_start or len(col) < len(teams) // 2:
            continue
        rk = LG.ranks(col)
        for t, r in rk.items():
            rank_hist[t].append([wk_start[w], r])
    prev_rows = {}
    for d in (_read(data / str(season - 1) / "season.json") or {}).get("standings") or []:
        for r in d.get("teams") or []:
            prev_rows[str(r.get("team"))] = r
    prev_tj = None
    champ_sb = None
    if final:
        for s in ((_read(data / "history.json") or {}).get("champions") or {}).get("seasons") or []:
            if int(s.get("season") or 0) == season and s.get("sb"):
                champ_sb = s["sb"]
    res = {t: results_of((tj.get(t) or {}).get("schedule") or [], t, asof) for t in teams}
    split = {}
    for t in teams:
        reg = [r for r in res[t] if r.get("gtype", "REG") == "REG"]
        split[t] = {side: tuple(sum(1 for r in reg if r["home"] == (side == "home") and r["res"] == x) for x in ("W", "L", "D")) for side in ("home", "away")}
    wpct = lambda x: (x[0] + 0.5 * x[2]) / max(1, sum(x))           # noqa: E731
    # a split rank counts only once two thirds of the league has played that many games on that side
    home_rank = LG.ranks({t: wpct(v["home"]) for t, v in split.items() if sum(v["home"]) >= 5})
    away_rank = LG.ranks({t: wpct(v["away"]) for t, v in split.items() if sum(v["away"]) >= 5})
    home_rank = home_rank if len(home_rank) >= 2 * len(teams) / 3 else {}
    away_rank = away_rank if len(away_rank) >= 2 * len(teams) / 3 else {}
    val = _read(sdir / "value.json") or {}
    from oddsmarkets.common import featured as FT
    cards = {}
    for t in teams:
        ti = info.get(t) or {}
        r = rows.get(t) or {}
        name = ti.get("name") or t
        short = ti.get("short") or name.split(" ")[-1]
        pos, of, div, gb = place.get(t, (None, None, ti.get("division"), None))
        team = {"name": name, "short": short, "abbr": t, "colour": ti.get("colour"), "alt": ti.get("alt"), "href": f"#/team/{t}",
                "league": LEAGUE, "group": div}
        rec = _rec(r.get("w"), r.get("l"), r.get("t"))
        stand = None
        if pos:
            back = f", {gb:g} game{'' if gb == 1 else 's'} back" if gb and gb > 0 else ""
            stand = {"pos": pos, "of": of, "group": div, "gb": gb if gb else None, "text": f"{FL.ordinal(pos)} in the {div}{back}"}
        rt = None
        if rating.get(t) is not None:
            rt = {"value": rating[t], "text": _fmt(rating[t], "+1"), "rank": rating_rank.get(t), "of": n_rated, "label": "Team rating"}
        now_blk = {"record": rec, "form": None if final else FL.form_letters(res[t], asof), "streak": None, "standing": stand, "rating": rt}
        sk_ = FL.streak_of(res[t], asof)
        if sk_ and not final:
            now_blk["streak"] = f"{sk_[0]}{sk_[1]}"
        chances, ctx_ch = [], []
        if not final:
            so = sim.get(t) or {}
            for key, lab, word in CHANCES:
                p = next((x for x in (_num(so.get(key)), _num((odds.get(t) or {}).get(key)), _num(r.get(key))) if x is not None), None)
                if p is None or (phase == "postseason" and key == "p_playoffs"):
                    continue
                ser = {d: (v or {}).get(t) for d, v in (rlog.get(key) or {}).items() if isinstance(v, dict)}
                chances.append({"key": key, "label": lab, "p": round(p, 4), "d7": FL.change_since(ser, asof, 7)})
                ctx_ch.append({"label": word, "series": ser})
        nxt = []
        for g in (upcoming_of((tj.get(t) or {}).get("schedule") or [], asof) if not final else []):
            home = g.get("home") == t
            o = str(g.get("away") if home else g.get("home"))
            oi = info.get(o) or {}
            h, a = g.get("home"), g.get("away")
            gt = str(g.get("gtype") or "REG")
            sig = {"title": [_num((odds.get(h) or {}).get("p_sb")), _num((odds.get(a) or {}).get("p_sb"))]}
            if gt in POST_NAME:
                sig["stage"] = {"WC": "playoff", "DIV": "quarter", "CON": "semi", "SB": "final"}[gt]
            else:
                sig["playoff"] = [_num((odds.get(h) or {}).get("p_playoffs")), _num((odds.get(a) or {}).get("p_playoffs"))]
            rv = _rivalry(name, oi.get("name"))
            if rv:
                sig["rivalry"] = rv
            sg = FT.significance({"sport": SPORT, "league": LEAGUE, "id": g.get("game_id"), "start": g.get("kickoff"), "status": "pre",
                                  "p_home": (g.get("model") or {}).get("p_home"), "sig": sig}, asof)
            gm = by_id.get(str(g.get("game_id"))) or {}
            mk = _num((gm.get("market") or {}).get("p_home")) if isinstance(gm.get("market"), dict) else None
            nxt.append({"id": str(g.get("game_id")), "start": g.get("kickoff"), "home": home,
                        "opp": {"name": oi.get("short") or oi.get("name") or o, "abbr": o, "colour": oi.get("colour"), "rank": rating_rank.get(o)},
                        "comp": POST_NAME.get(gt) or f"Week {g.get('week')}", "p": _side_p(g, t), "mkt": (round(mk if home else 1 - mk, 4) if mk is not None else None),
                        "why": sg["reasons"][:2], "href": f"#/game/{g.get('game_id')}",
                        "_score": sg["score"], "_reasons": sg["reasons"], "_rv": rv, "_short": oi.get("short") or o})
        note = None
        if not nxt:
            note = (f"Off-season. The {season + 1} schedule is not out yet." if final else
                    "The schedule is not out yet." if phase == "preseason" else "No games in the next few days.")
        last = None
        if res[t]:
            x = res[t][-1]
            oi = info.get(x["opp"]) or {}
            last = {"id": x["id"], "start": x["start"], "home": x["home"], "opp": {"name": oi.get("short") or oi.get("name") or x["opp"], "abbr": x["opp"], "colour": oi.get("colour")},
                    "score": [x["us"], x["them"]], "res": x["res"], "p": x["p"], "upset": FL.upset_flag(x["p"], x["res"]),
                    "comp": POST_NAME.get(str(x.get("gtype"))) or f"Week {x.get('week')}", "href": f"#/game/{x['id']}"}
        prow = [{"id": m["id"], "label": m.get("label") or m["id"], "pct": int(round(pcts[t][m["id"]])), "text": _fmt(vals[t].get(m["id"]), m.get("fmt"))}
                for m in spec if pcts[t].get(m["id"]) is not None]
        prow.sort(key=lambda x: -x["pct"])
        profile = {"strong": prow[:3], "weak": sorted(prow[3:], key=lambda x: x["pct"])[:2]} if len(prow) >= 5 else None
        players, top = _players(t, val)
        # ── the facts
        ctx = {"name": name, "short": short, "the": True, "phase": phase, "final": final, "league_name": "the NFL", "results": res[t],
               "rating_ranks": rank_hist.get(t) or []}
        ctx["pctl"] = [{"label": m.get("label") or m["id"], "rank": ranks[m["id"]][t], "of": len(ranks[m["id"]]), "tied": t in ties[m["id"]],
                        "text": _fmt(vals[t].get(m["id"]), m.get("fmt")), "model": bool(m.get("model"))}
                       for m in spec if m["id"] != "rating" and t in ranks[m["id"]]]
        if pct_rank.get(t) in (1, 2) and rec:
            ctx["best_record"] = {"record": rec, "scope": "league", "where": "the NFL", "rank": pct_rank[t]}
        elif pos == 1 and rec and div:
            ctx["best_record"] = {"record": rec, "scope": "group", "where": div}
        sp = split.get(t) or {}
        ctx["split"] = {"of": max(len(home_rank), len(away_rank)), "league": "the NFL",
                        "home": {"record": _rec(*sp.get("home", (None, None, None))), "rank": home_rank.get(t), "tied": t in _ties(home_rank)},
                        "away": {"record": _rec(*sp.get("away", (None, None, None))), "rank": away_rank.get(t), "tied": t in _ties(away_rank)}}
        lk = (lteams.get(t) or {}).get("luck") or {}
        if _num(lk.get("d")) is not None:
            ctx["luck"] = {"d": lk["d"], "unit": "wins", "basis": "their points for and against deserved"}
        rc = race.get(t) or {}
        if rc.get("sos") and phase == "season" and rc["sos"][1]:
            avg, rk, left = rc["sos"]
            ctx["sos"] = {"rank": rk, "of": len(teams), "left": left, "where": "the NFL", "text": f"{_fmt(avg, '+1')} points a game"}
        cl, el, mg = r.get("clinched") or {}, r.get("eliminated") or {}, r.get("magic") or {}
        if cl.get("division"):
            ctx["clinch"] = {"clinched": f"the {div}"}
        elif cl.get("playoffs"):
            ctx["clinch"] = {"clinched": "a playoff place"}
        elif el.get("playoffs"):
            ctx["clinch"] = {"eliminated": "the playoff race"}
        elif phase == "season" and _num(mg.get("playoffs")) is not None and 0 < mg["playoffs"] <= MAGIC_MAX:
            ctx["clinch"] = {"magic": int(mg["playoffs"]), "what": "a playoff place"}
        ctx["chances"] = ctx_ch
        if nxt:
            g0 = nxt[0]
            ctx["next"] = {"start": g0["start"], "opp": {"short": g0["_short"], "name": g0["opp"]["name"]}, "p": g0["p"],
                           "score": g0["_score"] if g0["_score"] >= BIG_GAME else None, "reasons": g0["_reasons"], "rivalry": g0["_rv"]}
        if top:
            ctx["players"] = [top]
        pv = prev_rows.get(t)
        if pv and _num(pv.get("w")) is not None and _num(r.get("w")) is not None:
            gp = int(r.get("w") or 0) + int(r.get("l") or 0) + int(r.get("t") or 0)
            if final:
                ctx["vs_last"] = {"now": [int(r["w"]), int(r["l"])], "last": [int(pv["w"]), int(pv["l"])], "season_last": season - 1, "full": True}
            elif gp >= 4:
                if prev_tj is None:
                    prev_tj = (_read(data / str(season - 1) / "teams.json") or {}).get("teams") or {}
                at = _record_after((prev_tj.get(t) or {}).get("schedule") or [], t, gp)
                if at:
                    ctx["vs_last"] = {"now": [int(r["w"]), int(r["l"])], "last": [at[0], at[1]], "season_last": season - 1}
        champ = None
        if champ_sb and str(champ_sb[0]) == t:
            ro = (info.get(str(champ_sb[1])) or {}).get("short") or str(champ_sb[1])
            ctx["champion"] = {"event": "Super Bowl", "season": season, "result": [champ_sb[2], champ_sb[3]], "opp": ro}
            champ = {"event": "Super Bowl", "season": season, "text": f"Won the {season} season's Super Bowl, {champ_sb[2]}{FL.DASH}{champ_sb[3]} over the {ro}."}
        if rt:
            ctx["rating"] = {"rank": rt["rank"], "of": rt["of"], "text": rt["text"], "unit": "points a game"}
        fx = FL.facts(ctx, asof)
        for g in nxt:
            for k in ("_score", "_reasons", "_rv", "_short"):
                g.pop(k, None)
        line = champ["text"] if champ else ((f"Season over: {rec}" if final else rec) + (f", {stand['text']}" if stand else "") + "." if rec else None)
        cards[t] = FL.make_card(site=SITE, sport=SPORT, scope=SCOPE, ident=t, team=team, asof=asof, phase=phase, season=season,
                                now=now_blk, chances=chances, next_games=nxt, next_note=note, last=last, line=line, profile=profile,
                                facts=fx, players=players, champion=champ)
    return FL.write_cards(out_dir or (data / "follow"), SCOPE, cards)


def main(argv=None) -> int:
    import argparse
    from oddsmarkets.nfl import analytics as an
    ap = argparse.ArgumentParser(description="Write the Gridiron's follow cards from the payloads on disk")
    ap.add_argument("--data", default=None)
    ap.add_argument("--now", default=None, help="ISO build clock (default now)")
    a = ap.parse_args(argv)
    data = Path(a.data) if a.data else an.data_root()
    s = build(data, FL._dt(a.now) if a.now else None)
    print(f"team: {s['n']} cards, {s['bytes'] / 1024:.0f} KB, largest {s['max']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
