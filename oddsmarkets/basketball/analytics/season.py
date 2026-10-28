"""
Season-level payloads: `season.json` (standings with tiebreak-correct seeds, the season simulation,
the projected bracket, ratings and their paths, Elo, power rankings, win totals against the market,
schedule difficulty and leaders), plus the league-wide `history.json`, `lab.json`, `markets.json`,
`calibration.json` and the league entry of the site-wide `index.json`.

Seeds come from the season simulation's tiebreak engine (`season_sim.Ranker`, the format's real
two-team and multi-team tiebreak orders) applied to the current table; "gb" is games behind the
conference leader. Power = the model net rating with the change in rank over the last 7 days.
Schedule difficulty = mean model net rating of the opponents played / still to play.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics.context import SeasonContext
from oddsmarkets.basketball.models import _io

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------- standings

def current_order(ctx: SeasonContext) -> dict:
    """{"order": {group: [tid in seed order]}, "seed": {tid: seed in its seeding group}, "fmt", "S0"} from the
    tiebreak engine on the current table."""
    from oddsmarkets.basketball.models import season_sim as SS
    S0 = SS.build_state(ctx.league, ctx.season, ctx.member_store)
    f = S0["fmt"]
    T = len(S0["teams"])
    rk = SS.Ranker(f, S0["conf_id"], S0["div_id"], S0["W"][None], S0["L"][None], S0["H"][None].astype(np.int16), S0["CW"][None],
                   S0["CL"][None], S0["DW"][None], S0["DL"][None], S0["PD"][None], S0["HPD"][None].astype(np.float32),
                   np.random.default_rng(ctx.season))
    if f.seeding == "league":
        groups = {"League": list(range(T))}
    else:
        groups = {S0["conf_names"][c]: list(np.nonzero(S0["conf_id"] == c)[0]) for c in np.unique(S0["conf_id"])}
    order, seed = {}, {}
    for gname, mem in groups.items():
        o = [S0["teams"][int(i)] for i in rk.rank(mem)[0]]
        order[gname] = o
        for k, t in enumerate(o):
            seed[t] = k + 1
    return {"order": order, "seed": seed, "fmt": f, "S0": S0}


def standings(ctx: SeasonContext) -> dict:
    """{conf: [rows]} (PAYLOADS season.json), conferences in seed order within each."""
    co = current_order(ctx)
    S0 = co["S0"]
    idx = S0["idx"]
    teams = S0["teams"]
    rec: dict[str, dict] = {t: {"home": [0, 0], "away": [0, 0], "res": []} for t in teams}
    for g in sorted(ctx.games.values(), key=lambda g: str(g.get("date") or "")):
        if g.get("stype") != "reg" or g.get("status") != "post" or g.get("hs") is None:
            continue
        h, a = str(g["home"]), str(g["away"])
        if h not in rec or a not in rec:
            continue
        hw = int(g["hs"]) > int(g["as"])
        rec[h]["home"][0 if hw else 1] += 1
        rec[a]["away"][1 if hw else 0] += 1
        rec[h]["res"].append("W" if hw else "L")
        rec[a]["res"].append("L" if hw else "W")
    by_conf: dict[str, list[str]] = {}
    for t in teams:
        by_conf.setdefault(S0["conf_names"][S0["conf_id"][idx[t]]], []).append(t)
    out = {}
    for conf, mem in by_conf.items():
        mem.sort(key=lambda t: co["seed"].get(t, 99))
        if co["fmt"].seeding == "league":
            mem.sort(key=lambda t: co["seed"].get(t, 99))
        lead = mem[0] if mem else None
        rows = []
        for t in mem:
            i = idx[t]
            w, l = int(S0["W"][i]), int(S0["L"][i])
            lw, ll = (int(S0["W"][idx[lead]]), int(S0["L"][idx[lead]])) if lead else (w, l)
            res = rec[t]["res"]
            streak = ""
            if res:
                k = 1
                while k < len(res) and res[-k - 1] == res[-1]:
                    k += 1
                streak = f"{res[-1]}{k}"
            l10 = res[-10:]
            rows.append({"team": t, "w": w, "l": l, "pct": round(w / (w + l), 3) if w + l else None,
                         "gb": ((lw - w) + (l - ll)) / 2.0, "conf_w": int(S0["CW"][i]), "conf_l": int(S0["CL"][i]),
                         "div_w": int(S0["DW"][i]), "div_l": int(S0["DL"][i]), "home": rec[t]["home"], "away": rec[t]["away"],
                         "l10": [l10.count("W"), l10.count("L")], "streak": streak, "pd": int(S0["PD"][i]),
                         "seed": co["seed"].get(t), "division": S0["div_names"][S0["div_id"][i]]})
        out[conf] = rows
    return out


# ---------------------------------------------------------------------------------------------- season.json

def _fmt(ctx: SeasonContext) -> dict:
    from oddsmarkets.basketball.models.config import fmt as get_fmt
    f = get_fmt(ctx.league, ctx.season)
    divs = {}
    for t in ctx.teams:
        info = an.team_info(ctx.store, t)
        if info["conference"]:
            divs.setdefault(info["conference"], set()).add(info["division"] or info["conference"])
    return {"conferences": sorted(divs), "divisions": {c: sorted(v) for c, v in divs.items()}, "games": f.games,
            "playin": bool(f.playin), "series": list(f.series), "rounds": list(f.rounds), "seeding": f.seeding,
            "playoff_teams": f.playoff_teams, "verified": f.verified}


def leaders(cat: dict, n: int = 10) -> dict:
    rows = (cat or {}).get("players") or {}
    q = {p: r for p, r in rows.items() if r.get("qualified")}
    stats = {"pts": "pts_g", "reb": "reb_g", "ast": "ast_g", "stl": "stl_g", "blk": "blk_g", "3pm": "tpm_g", "hpm": "hpm", "ts": "ts"}
    out = {}
    for name, key in stats.items():
        vals = [(p, r["values"].get(key)) for p, r in q.items() if r["values"].get(key) is not None]
        vals.sort(key=lambda kv: -kv[1])
        out[name] = [[p, v] for p, v in vals[:n]]
    return out


def schedule_difficulty(ctx: SeasonContext) -> dict:
    rt = (ctx.ratings or {}).get("teams") or {}
    played: dict[str, list] = {}
    rem: dict[str, list] = {}
    for g in ctx.games.values():
        if g.get("stype") not in ("reg", "cup"):
            continue
        h, a = str(g.get("home")), str(g.get("away"))
        tgt = played if g.get("status") == "post" else rem if g.get("status") == "pre" else None
        if tgt is None:
            continue
        tgt.setdefault(h, []).append((rt.get(a) or {}).get("net"))
        tgt.setdefault(a, []).append((rt.get(h) or {}).get("net"))
    return {t: {"played": an.rnd(an.mean(played.get(t, [])), 2), "remaining": an.rnd(an.mean(rem.get(t, [])), 2),
                "n_played": len(played.get(t, [])), "n_remaining": len(rem.get(t, []))} for t in ctx.teams}


def power(ctx: SeasonContext, ratings_7d: dict | None) -> list[list]:
    rt = (ctx.ratings or {}).get("teams") or {}
    now = sorted((t for t in ctx.teams if t in rt), key=lambda t: -rt[t]["net"])
    before = {}
    if ratings_7d:
        b = sorted((t for t in ctx.teams if t in ratings_7d), key=lambda t: -ratings_7d[t]["net"])
        before = {t: k + 1 for k, t in enumerate(b)}
    return [[t, an.rnd(rt[t]["net"], 2), (before[t] - (k + 1)) if t in before else None] for k, t in enumerate(now)]


def win_totals(ctx: SeasonContext) -> dict | None:
    fut = ctx.futures or {}
    wt = fut.get("win_totals") or {}
    sim = (ctx.sim or {}).get("teams") or {}
    if not wt:
        return None
    out = {}
    for t, v in wt.items():
        line = an.fnum(v.get("line"))
        dist = (sim.get(t) or {}).get("win_dist")
        pm = float(sum(p for k, p in enumerate(dist) if k > line)) if dist and line is not None else None
        out[t] = {"line": line, "p_over_model": an.rnd(pm, 4), "p_over_market": an.rnd(v.get("p_over"), 4),
                  "ladder": v.get("ladder")}
    return out


def build_season(ctx: SeasonContext, players_cat: dict | None, ratings_7d: dict | None) -> dict:
    rt = ctx.ratings or {}
    rteams = rt.get("teams") or {}
    order = sorted((t for t in ctx.teams if t in rteams), key=lambda t: -rteams[t]["net"])
    ratings = {t: {"off": an.rnd(rteams[t]["off"], 2), "def": an.rnd(rteams[t]["def"], 2), "net": an.rnd(rteams[t]["net"], 2),
                   "pace": an.rnd(rteams[t]["pace"], 2), "se_net": an.rnd(rteams[t]["se_net"], 2), "games": rteams[t].get("games"),
                   "rank": k + 1} for k, t in enumerate(order)}
    sim = ctx.sim
    out = {"ok": True, "league": ctx.league, "season": ctx.season, "updated_at": an.now(), "phase": ctx.phase, "format": _fmt(ctx),
           "teams": {t: an.team_info(ctx.store, t) for t in ctx.teams},
           "standings": _safe(lambda: standings(ctx), {}),
           "sim": None, "bracket": None,
           "ratings": ratings, "hca": an.rnd(rt.get("hca_pts"), 2), "league_ortg": an.rnd(rt.get("league_ortg"), 2),
           "league_pace": an.rnd(rt.get("league_pace"), 2),
           "rating_paths": {t: v for t, v in (rt.get("paths") or {}).items() if t in ctx.teams},
           "elo": {t: an.rnd(v, 1) for t, v in (ctx.elo_season.get("end") or {}).items() if t in ctx.teams},
           "power": power(ctx, ratings_7d),
           "schedule_difficulty": schedule_difficulty(ctx), "leaders": leaders(players_cat)}
    if sim and sim.get("ok", True) and sim.get("teams"):
        st = {}
        for t, v in sim["teams"].items():
            st[t] = _io.clean(v, 4)
        out["sim"] = {"n_sims": sim.get("n_sims"), "teams": st, "notes": sim.get("notes"), "remaining_games": sim.get("remaining_games"),
                      "runtime_s": sim.get("runtime_s"), "hca": an.rnd(sim.get("hca"), 2), "sigma_noise": an.rnd(sim.get("sigma_noise"), 3)}
        out["bracket"] = _io.clean(sim.get("bracket"), 4)
    elif sim is not None:
        out["sim"] = {"ok": False, "reason": sim.get("reason")}
    out["postseason"] = _safe(lambda: postseason(ctx), None)
    return out


def round_label(league: str, k: int, n: int) -> str:
    """The round's name by its place (1-based k of n rounds): ESPN calls every WNBA round after the first "Playoff
    Series", so names come from the bracket's depth, never the feed. NBA: First round, Conference semi-finals,
    Conference finals, NBA Finals; WNBA: First round, (Second round,) Semi-finals, WNBA Finals."""
    from_end = n - k
    if from_end <= 0:
        return f"{league.upper()} Finals"
    if league == "nba":
        names = ["Conference finals", "Conference semi-finals", "First round"]
    else:
        names = ["Semi-finals", "Second round", "First round"] if n >= 4 else ["Semi-finals", "First round"]
    return names[from_end - 1] if from_end - 1 < len(names) else f"Round {k}"


def normalise_rounds(series: list[dict], league: str, fmt: dict | None, conf_of: dict | None = None,
                     finished: bool = False) -> list[dict]:
    """Give each playoff series (stype post) its place in the bracket: `rnum` (1-based round), `rkey` (the format's
    round key: r1, semis, conf_finals, finals), `round` (the round's name, normalised: round_label), `round_src` (the
    feed's own name), `conf` (both teams' conference before the NBA Finals) and `winner` (the team that reached the
    wins needed, or the one that played on). The round is the depth: one more than the most series either team had
    already played, in start order, which holds with byes (WNBA 2016-21) and old best-of-five first rounds. Play-in
    series are left as they are. Mutates and returns `series`."""
    fmt = fmt or {}
    keys = list(fmt.get("rounds") or [])
    best = list(fmt.get("series") or [])
    post = [s for s in series if s.get("stype") == "post"]
    post.sort(key=lambda s: min((str(x.get("date") or "") for x in s.get("games") or []), default=""))
    played: dict[str, int] = {}
    for s in post:
        t = [str(x) for x in s.get("teams") or []]
        s["rnum"] = 1 + max([played.get(x, 0) for x in t] or [0])
        for x in t:
            played[x] = played.get(x, 0) + 1
    n = max([len(keys)] + [s["rnum"] for s in post] or [1])
    for s in post:
        k = s["rnum"]
        if s.get("round") is not None and "round_src" not in s:
            s["round_src"] = s.get("round")
        s["round"] = round_label(league, k, n)
        off = n - len(keys)
        s["rkey"] = keys[k - 1 - off] if keys and 0 <= k - 1 - off < len(keys) else ("finals" if k == n else f"r{k}")
        t = [str(x) for x in s.get("teams") or []]
        if conf_of and league == "nba" and k < n and len(t) == 2 and conf_of.get(t[0]) and conf_of.get(t[0]) == conf_of.get(t[1]):
            s["conf"] = conf_of[t[0]]
        w = s.get("wins") or {}
        bo = best[min(k - 1 - off, len(best) - 1)] if best and k - 1 - off >= 0 else None
        need = (bo // 2 + 1) if bo else None
        win = next((x for x in t if need and int(w.get(x) or 0) >= need), None)
        if win is None:
            later = [x for x in t if any(o.get("rnum", 0) > k and x in [str(y) for y in o.get("teams") or []] for o in post)]
            win = later[0] if len(later) == 1 else None
        if win is None and "wins series" in str(s.get("summary") or "").lower():
            win = max(t, key=lambda x: int(w.get(x) or 0)) if t else None
        if win is None and finished and k == n and t and int(w.get(t[0]) or 0) != int(w.get(t[-1]) or 0):
            win = max(t, key=lambda x: int(w.get(x) or 0))
        s["winner"] = win
        s["best_of"] = bo
    return series


def postseason(ctx: SeasonContext) -> dict | None:
    """Played play-in and playoff games grouped by series (the actual bracket so far), each playoff series with its
    normalised round (normalise_rounds)."""
    series: dict[str, dict] = {}
    for gid, g in sorted(ctx.games.items(), key=lambda kv: str(kv[1].get("date") or "")):
        if g.get("stype") not in ("post", "playin"):
            continue
        h, a = str(g["home"]), str(g["away"])
        key = "|".join(sorted((h, a))) + "|" + str(g.get("stype"))
        s = series.setdefault(key, {"teams": sorted((h, a)), "stype": g.get("stype"), "games": [], "wins": {h: 0, a: 0},
                                    "round": (g.get("series") or {}).get("round")})
        s["games"].append({"id": gid, "date": g.get("date"), "home": h, "away": a, "hs": g.get("hs"), "as": g.get("as"),
                           "status": g.get("status")})
        if g.get("status") == "post" and g.get("hs") is not None:
            w = h if g["hs"] > g["as"] else a
            s["wins"][w] = s["wins"].get(w, 0) + 1
        if (g.get("series") or {}).get("summary"):
            s["summary"] = g["series"]["summary"]
    if not series:
        return None
    conf_of = {t: an.team_info(ctx.store, t).get("conference") for t in ctx.teams}
    pending = any(g.get("stype") == "post" and g.get("status") in ("pre", "in") for g in ctx.games.values())
    return {"series": normalise_rounds(list(series.values()), ctx.league, _fmt(ctx), conf_of, finished=not pending)}


def series_round(ctx: SeasonContext, g: dict) -> dict | None:
    """A game's `series` block with the normalised round name (the game card and the game page): ESPN's own name
    for every WNBA round after the first is "Playoff Series"."""
    ser = g.get("series")
    if not ser or g.get("stype") != "post":
        return ser
    cache = getattr(ctx, "_round_names", None)
    if cache is None:
        cache = {}
        try:
            for s in (postseason(ctx) or {}).get("series") or []:
                if s.get("stype") == "post":
                    cache["|".join(sorted(str(x) for x in s.get("teams") or []))] = s.get("round")
        except Exception:  # noqa: BLE001
            cache = {}
        try:
            ctx._round_names = cache
        except Exception:  # noqa: BLE001
            pass
    name = cache.get("|".join(sorted((str(g.get("home")), str(g.get("away"))))))
    if not name:
        return ser
    out = dict(ser)
    if out.get("round") and out.get("round") != name:
        out["round_src"] = out.get("round")
    out["round"] = name
    return out


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("season block failed: %s", exc, exc_info=True)
        return default


# ---------------------------------------------------------------------------------------------- history

def season_outcome(store: dict) -> dict:
    """{"champion","runner_up"} from the store's last finished playoff game (None while the playoffs run)."""
    from oddsmarkets.basketball.models.backtest import season_outcomes
    games = an.real_games(store)
    pend = [g for g in (store.get("games") or {}).values() if g.get("stype") == "post" and g.get("status") in ("pre", "in")]
    if pend:
        return {"champion": None, "runner_up": None}
    o = season_outcomes({"games": games})
    champ = o.get("champion")
    runner = next((t for t in o.get("finalists") or [] if t != champ), None)
    return {"champion": champ, "runner_up": runner}


def history(league: str, seasons: list[int], elo_hist: dict | None) -> dict:
    """history.json: champions (from the stores), MVP and best record per season, all-time Elo peaks."""
    from oddsmarkets.basketball.models import award_winners as AW
    rows = []
    names = {}
    for s in seasons:
        st = an.load_store(league, s)
        if not st.get("games"):
            continue
        for t, v in (st.get("teams") or {}).items():
            names[t] = v.get("name") or names.get(t)
        oc = season_outcome(st)
        best = None
        rec: dict[str, list[int]] = {}
        for g in an.real_games(st, ("reg",)).values():
            if g.get("status") == "post" and g.get("hs") is not None:
                hw = int(g["hs"]) > int(g["as"])
                for t, w in ((str(g["home"]), hw), (str(g["away"]), not hw)):
                    r = rec.setdefault(t, [0, 0])
                    r[0 if w else 1] += 1
        if rec:
            t = max(rec, key=lambda k: (rec[k][0] / max(1, sum(rec[k])), rec[k][0]))
            best = [t, rec[t][0], rec[t][1]]
        mvp = (AW.winner_names(league, "mvp", s) or [None])[0]
        rows.append({"season": s, "champion": oc["champion"], "runner_up": oc["runner_up"],
                     "champion_name": an.team_info(st, oc["champion"])["name"] if oc["champion"] else None,
                     "mvp": mvp, "finals_mvp": None, "best_record": best})
    champions = sorted([[r["season"], r["champion"]] for r in rows if r["champion"]], key=lambda x: x[0])
    peaks = []
    if elo_hist:
        best: dict[str, tuple] = {}
        for g in elo_hist.get("games") or []:
            for t, e in ((g[3], g[8]), (g[4], g[9])):
                if t not in best or e > best[t][0]:
                    best[t] = (e, g[2])
        peaks = sorted(({"team": t, "name": names.get(t), "peak": round(v[0], 1), "season": v[1]} for t, v in best.items()),
                       key=lambda r: -r["peak"])[:40]
    return {"ok": True, "league": league, "updated_at": an.now(), "seasons": sorted(rows, key=lambda r: -r["season"]),
            "champions": champions, "first_season": min((r["season"] for r in rows), default=None), "elo_all_time": peaks,
            "team_names": names, "notes": ["champions come from the season stores (ESPN box scores from 1997); there is no earlier source"]}


# ---------------------------------------------------------------------------------------------- lab

LAB_MIN_SHARE = 0.5


# The value model's columns appended to the lab (value.json per season, joined on the player id): our wins above
# replacement, so the lab can chart it beside HPM (METRICS_SHOWCASE.md, 24 Oct 2026).
LAB_VALUE_METRICS = [an.metric("war", "Wins above replacement (WAR)", "Impact", "1",
                               desc="Wins the player added over a replacement-level player in the minutes played, from HPM.")]


def value_columns(value_payload: dict | None) -> dict[str, dict]:
    """{player id: {"war": ...}} from one season's value.json (cols / rows)."""
    cols = (value_payload or {}).get("cols") or []
    if "id" not in cols:
        return {}
    i_id = cols.index("id")
    idx = {m["key"]: cols.index(m["key"]) for m in LAB_VALUE_METRICS if m["key"] in cols}
    return {str(r[i_id]): {k: r[i] for k, i in idx.items()} for r in (value_payload or {}).get("rows") or []
            if isinstance(r, list) and len(r) == len(cols)}


def lab_payload(league: str, catalogues: dict[int, dict], value: dict[int, dict[str, dict]] | None = None) -> dict:
    """Column-oriented: every player-season with at least half the season's qualifying minutes. `value`: {season:
    {player id: {"war": ...}}} (value_columns of each season's value.json) adds the value model's columns. `role` is
    the spec's peer group (G / W / B: the catalogue's `role`, else value.classify_roles on that season's catalogue,
    the same rule), for the Lab's "Compare within: Position"."""
    from oddsmarkets.basketball.analytics.players import METRICS
    from oddsmarkets.basketball.analytics import value as VAL
    value = value or {}
    vmetrics = [m for m in LAB_VALUE_METRICS if any(m["key"] in row for rows in value.values() for row in rows.values())]
    keys = [m["key"] for m in METRICS]
    vkeys = [m["key"] for m in vmetrics]
    fields = ["id", "name", "team", "season", "pool", "gp", "min", "qualified", "role"] + keys + vkeys
    rows = []
    years = []
    for s in sorted(catalogues):
        cat = catalogues[s] or {}
        pl = cat.get("players") or {}
        if not pl:
            continue
        years.append(int(s))
        floor = LAB_MIN_SHARE * float(cat.get("min_floor") or 0)
        roles = VAL.classify_roles(cat)[0] if any(not r.get("role") for r in pl.values()) else {}
        for pid, r in pl.items():
            if (r.get("min") or 0) < floor:
                continue
            v = r.get("values") or {}
            vv = (value.get(int(s)) or value.get(s) or {}).get(str(pid)) or {}
            rows.append([pid, r.get("name"), r.get("team"), int(s), r.get("pool"), r.get("gp"), r.get("min"), bool(r.get("qualified")),
                         r.get("role") or roles.get(pid)]
                        + [v.get(k) for k in keys] + [vv.get(k) for k in vkeys])
    return {"ok": True, "league": league, "updated_at": an.now(), "fields": fields, "metrics": METRICS + vmetrics, "rows": rows, "years": years}


# ---------------------------------------------------------------------------------------------- markets

def markets_payload(ctx: SeasonContext) -> dict:
    """markets.json: futures with the model beside them, per-game model v market for the next 3 days, win totals."""
    from oddsmarkets.basketball.analytics.games import market_line, model_line
    fut = ctx.futures
    sim = (ctx.sim or {}).get("teams") or {}
    games = {}
    for gid, g in ctx.games.items():
        if g.get("status") not in ("pre", "in"):
            continue
        from oddsmarkets.basketball.models._games import local_day
        d = local_day(g)
        if d is None or d < ctx.today or d > ctx.today + timedelta(days=3):
            continue
        m = _safe(lambda: model_line(ctx, g))
        mk = _safe(lambda: market_line(ctx, g))
        edge = (m["p_home"] - mk["p_home"]) if m and mk and mk.get("p_home") is not None else None
        games[gid] = {"season": ctx.season, "home": str(g["home"]), "away": str(g["away"]), "date": g.get("date"),
                      "model": {"p_home": an.rnd((m or {}).get("p_home"), 4), "margin": an.rnd((m or {}).get("margin"), 2),
                                "total": an.rnd((m or {}).get("total"), 1), "spread_fair": an.rnd((m or {}).get("spread_fair"), 1)} if m else None,
                      "market": mk, "edge": an.rnd(edge, 4)}
    model_title = {t: an.rnd(v.get("p_title"), 4) for t, v in sim.items()}
    model_conf = {t: an.rnd(v.get("p_conf"), 4) for t, v in sim.items()}
    return {"ok": True, "league": ctx.league, "season": ctx.season, "updated_at": an.now(),
            "futures": _io.clean(fut, 4) if fut else None, "model": {"champion": model_title, "conference": model_conf,
                                                                       "playoffs": {t: an.rnd(v.get("p_playoffs"), 4) for t, v in sim.items()}},
            "games": games, "win_totals": _safe(lambda: win_totals(ctx)), "fetched": bool(ctx.fetch_markets)}


# ---------------------------------------------------------------------------------------------- calibration

def calibration(league: str, data_root: Path, seasons: list[int] | None = None) -> dict:
    """The cached walk-forward backtest (<cache>/backtest_<league>.json; without it, the committed copy, as in CI),
    plus "winprob" (our live win probability against ESPN's, `winprob.calibration`) and "shots" (xPTS by zone and
    shot type, `shots.calibration_table`) for the latest season that has their inputs on this machine."""
    from oddsmarkets.basketball.models import backtest as BT
    p = an.cache_root() / f"backtest_{league}.json"
    prev = data_root / league / "calibration.json"
    old = (an.read_json(prev) if prev.exists() else None) or {}
    cached = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    # The newer backtest wins: CI restores an Actions cache whose backtest can predate the committed copy (the
    # promoted NBA model's 21 Oct calibration never reached the live site, which kept serving the 1 Oct backtest).
    if cached is not None and old.get("ok") and str(old.get("generated_at") or "") > str(cached.get("generated_at") or ""):
        cached = None
    if cached is not None:
        d = cached
        d.update({"ok": True, "updated_at": d.get("generated_at") or an.now(), "summary": BT.summary_table(d)})
    elif old.get("ok"):
        d = old
    else:
        d = {"ok": False, "reason": "no cached backtest (run oddsmarkets.basketball.models.backtest.backtest())", "updated_at": an.now()}
    wp = _safe(lambda: winprob_calibration(league, seasons or an.seasons_on_disk(league)))
    d["winprob"] = wp or old.get("winprob")
    sh = _safe(lambda: shots_calibration(league, seasons or an.seasons_on_disk(league)))
    d["shots"] = sh or old.get("shots")
    return d


def winprob_calibration(league: str, seasons: list[int]) -> dict | None:
    from oddsmarkets.basketball.models import winprob as W
    for s in sorted(seasons, reverse=True):
        if not an.has_pbp_dir(league, s):
            continue
        r = W.for_season(league, s)
        if r.get("ok") and (r.get("calibration") or {}).get("n"):
            m = r.get("model") or {}
            return {"season": s, **_io.clean(r["calibration"], 5),
                    "model": {k: m.get(k) for k in ("K", "beta", "features", "n", "version")}}
    return None


def shots_calibration(league: str, seasons: list[int]) -> dict | None:
    from oddsmarkets.basketball.models import shots as SH
    for s in sorted(seasons, reverse=True):
        r = SH.for_season(league, s)
        if r.get("ok"):
            return {"season": s, "n_shots": r.get("n_shots"), "by_zone": r.get("calibration"), "by_type": r.get("calibration_type"),
                    "curve": r.get("curve")}
    return None


# ---------------------------------------------------------------------------------------------- index

def league_index(league: str, ctx: SeasonContext | None, seasons: list[int], hist: dict | None, today: date) -> dict:
    from oddsmarkets.basketball.analytics.games import cards
    cur = ctx.season if ctx else (max(seasons) if seasons else None)
    out = {"name": an.LEAGUE_NAMES.get(league, league.upper()), "current_season": cur, "seasons": sorted(seasons, reverse=True),
           "phase": ctx.phase if ctx else "offseason", "today": [], "next_games": [], "last_games": [], "teams": {},
           "champions": (hist or {}).get("champions") or []}
    if ctx:
        out.update(_safe(lambda: cards(ctx, today), {}) or {})
        out["teams"] = {t: {k: v for k, v in an.team_info(ctx.store, t).items()} for t in ctx.teams}
    return out
