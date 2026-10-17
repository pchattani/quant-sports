"""
season.json (standings by division with records, ratings and schedule strength; simulation odds; draft order; the
playoff bracket with odds; unit ratings with week-by-week history), schedule.json, weeks/<w>.json and the markets
payload.

Seeding "if the season ended today" applies the verified NFL tiebreakers (oddsmarkets.nfl.tiebreak, builder A).
Simulation odds come from our season_sim; when it is not available the season page still has standings,
current seeds and the draft order by record, and the odds blocks are null with the reason.
"""
from __future__ import annotations

import logging
from typing import Any

from oddsmarkets.nfl import analytics as an
from oddsmarkets.nfl.analytics.context import GTYPE_ORDER, SeasonContext

logger = logging.getLogger(__name__)
ROUND_NAMES = {"WC": "Wild Card", "DIV": "Divisional", "CON": "Conference Championship", "SB": "Super Bowl"}


def _final_reg(ctx: SeasonContext) -> list[dict]:
    return [g for g in ctx.games.values() if g.get("gtype") == "REG" and g.get("status") == "final" and g.get("hs") is not None]


def seeds_today(ctx: SeasonContext) -> dict:
    """{conf: {"seeds": [abbr x7], "division_winners", "order"}} by the tiebreakers on completed games."""
    out: dict = {}
    try:
        from oddsmarkets.nfl import tiebreak
        games = [{"home": g["home"], "away": g["away"], "hs": int(g["hs"]), "as": int(g["as"]), "week": g.get("week")} for g in _final_reg(ctx)]
        if not games:
            return {}
        tb = tiebreak.Table(games, ctx.season)
        for conf in ("AFC", "NFC"):
            r = tb.seed_conference(conf)
            out[conf] = {k: r.get(k) for k in ("seeds", "division_winners", "order")}
    except Exception as exc:                                     # noqa: BLE001
        logger.info("seeds today %s: %s", ctx.season, exc)
        ctx.model_errors["seeds_today"] = f"{type(exc).__name__}: {exc}"
    return out


def sos(ctx: SeasonContext, rating: dict[str, float]) -> dict[str, dict]:
    """Strength of schedule: mean opponent rating of games played and of games remaining (regular season)."""
    out: dict[str, dict] = {t: {"played": [], "left": []} for t in ctx.teams}
    for g in ctx.games.values():
        if g.get("gtype") != "REG":
            continue
        k = "played" if g.get("status") == "final" else "left"
        for t, o in ((g.get("home"), g.get("away")), (g.get("away"), g.get("home"))):
            if t in out and rating.get(o) is not None:
                out[t][k].append(rating[o])
    return {t: {"sos": an.rnd(an.mean(v["played"]), 2), "sos_left": an.rnd(an.mean(v["left"]), 2), "games_left": len(v["left"])}
            for t, v in out.items()}


def opp_win_pct(ctx: SeasonContext, recs: dict[str, dict]) -> dict[str, float]:
    """The NFL's strength of schedule: the combined win percentage of the opponents played (ties half)."""
    out = {}
    finals = _final_reg(ctx)
    for t in ctx.teams:
        w = n = 0.0
        for g in finals:
            if t in (g["home"], g["away"]):
                o = g["away"] if g["home"] == t else g["home"]
                r = recs.get(o) or {}
                w += r.get("w", 0) + 0.5 * r.get("t", 0)
                n += r.get("w", 0) + r.get("l", 0) + r.get("t", 0)
        out[t] = w / n if n else None
    return out


def draft_order(ctx: SeasonContext, recs: dict[str, dict], sim: dict | None, seeds: dict) -> list[dict]:
    """Draft order: the simulation's expected pick and pick-1 odds when available, else today's order by record
    (non-playoff teams first, worst record first; strength-of-schedule ties broken by lower opponents' win share)."""
    sim_t = (sim or {}).get("teams") or {} if (sim or {}).get("ok") else {}
    playoff = {t for c in seeds.values() for t in (c.get("seeds") or [])}
    opp_pct = opp_win_pct(ctx, recs)
    rows = []
    for t, r in recs.items():
        s = sim_t.get(t) or {}
        rows.append({"team": t, "w": r.get("w"), "l": r.get("l"), "t": r.get("t"), "pct": r.get("pct"), "sos_pct": an.rnd(opp_pct.get(t), 3),
                     "in_playoffs_today": t in playoff, "mean_pick": an.rnd(s.get("mean_pick"), 2),
                     "p_first_pick": an.rnd(s.get("p_first_pick"), 4), "p_top5": an.rnd(s.get("p_top5"), 4),
                     "p_top10": an.rnd(s.get("p_top10"), 4), "pick_dist": s.get("pick_dist")})
    if any(r["mean_pick"] is not None for r in rows):
        rows.sort(key=lambda r: (r["mean_pick"] if r["mean_pick"] is not None else 99))
        src = "simulation"
    else:
        rows.sort(key=lambda r: (r["in_playoffs_today"], r["pct"] if r["pct"] is not None else 0.5, r["sos_pct"] if r["sos_pct"] is not None else 0.5))
        src = "record"
    for i, r in enumerate(rows):
        r["pick_today"] = i + 1
        r["source"] = src
    return rows


def bracket(ctx: SeasonContext, sim: dict | None, seeds: dict, cards: list[dict]) -> dict:
    """Actual postseason games by round (with model and market prices), today's seeds, and the simulation's bracket
    odds (per team: reach each round / win the title)."""
    rounds: dict[str, list] = {}
    for c in cards:
        if c.get("gtype") in ROUND_NAMES:
            rounds.setdefault(c["gtype"], []).append(c)
    sim_ok = bool((sim or {}).get("ok"))
    return {"rounds": [{"key": k, "name": ROUND_NAMES[k], "games": rounds.get(k, [])} for k in ("WC", "DIV", "CON", "SB")],
            "seeds_today": seeds, "sim": (sim or {}).get("bracket") if sim_ok else None,
            "odds": {t: {k: v.get(k) for k in ("p_playoffs", "p_bye", "p_conf", "p_sb")}
                     for t, v in ((sim or {}).get("teams") or {}).items()} if sim_ok else None}


def build(ctx: SeasonContext, tms: dict | None, sim: dict | None, cards: list[dict]) -> dict | None:
    from oddsmarkets.nfl.analytics import teams as TM
    recs = TM.records(ctx)
    tt = (tms or {}).get("teams") or {}
    rating = {t: an.fnum((r.get("values") or {}).get("rating")) for t, r in tt.items()}
    sc = sos(ctx, rating)
    opp_pct = opp_win_pct(ctx, recs)
    seeds = seeds_today(ctx)
    seed_of = {t: (i + 1, c) for c, v in seeds.items() for i, t in enumerate(v.get("seeds") or [])}
    sim_ok = bool((sim or {}).get("ok"))
    sim_t = (sim or {}).get("teams") or {} if sim_ok else {}
    divisions: dict[str, list] = {}
    for t, info in ctx.teams.items():
        r = recs.get(t) or {}
        s = sim_t.get(t) or {}
        row = {"team": t, "name": info.get("name"), "colour": info.get("colour"), "w": r.get("w"), "l": r.get("l"), "t": r.get("t"),
               "pct": r.get("pct"), "pf": r.get("pf"), "pa": r.get("pa"), "diff": r.get("diff"), "home": r.get("home"), "away": r.get("away"),
               "div": r.get("div"), "conf": r.get("conf"), "streak": r.get("streak"), "last5": r.get("last5"),
               "rating": an.rnd(rating.get(t), 2), **(sc.get(t) or {}), "sos_pct": an.rnd(opp_pct.get(t), 3),
               "seed_today": (seed_of.get(t) or (None,))[0]}
        if sim_ok:
            row.update({k: an.rnd(s.get(k), 4) for k in ("p_playoffs", "p_div", "p_bye", "p_conf", "p_sb", "p_1seed")})
            row["mean_wins"] = an.rnd(s.get("mean_wins"), 2)
            for k in ("p_wildcard", "w_p05", "w_p95", "p_first_pick", "mean_pick"):
                row[k] = an.rnd(s.get(k), 4)
            for k in ("seed_dist", "win_dist", "magic", "tragic", "clinched", "eliminated", "next_game", "p_reach"):
                if k in s:
                    row[k] = an.clean(s[k])
        divisions.setdefault(info.get("division") or "-", []).append(row)
    for d, rows in divisions.items():
        order = None
        try:
            from oddsmarkets.nfl import tiebreak
            games = [{"home": g["home"], "away": g["away"], "hs": int(g["hs"]), "as": int(g["as"])} for g in _final_reg(ctx)]
            if games:
                order = tiebreak.Table(games, ctx.season).division_order(d)
        except Exception:                                        # noqa: BLE001
            order = None
        if order:
            pos = {t: i for i, t in enumerate(order)}
            rows.sort(key=lambda r: pos.get(r["team"], 99))
        else:
            rows.sort(key=lambda r: (-(r["pct"] or 0), -(r["diff"] or 0)))
    standings = [{"division": d, "conference": d.split()[0] if d != "-" else None, "teams": rows}
                 for d, rows in sorted(divisions.items())]
    ratings = {t: {"values": {k: (r.get("values") or {}).get(k) for k in ("rating", "off_rating", "def_rating", "off_epa", "def_epa",
                                                                        "off_pass_epa", "off_rush_epa", "def_pass_epa", "def_rush_epa", "st_epa_g")},
                   "history": r.get("history"), "source": (r.get("units") or {}).get("source")} for t, r in tt.items()}
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "phase": ctx.phase, "week": ctx.week, "standings": standings,
            "sos_units": {"sos": "mean team rating of opponents played (points per game v an average team)",
                          "sos_left": "mean team rating of opponents still to play (same units)",
                          "sos_pct": "opponents' combined win percentage, games played (the NFL's strength of schedule)"},
            "seeds_today": seeds, "sim": {"ok": sim_ok, "n": (sim or {}).get("n"), "reason": None if sim_ok else (sim or {}).get("reason"),
                                          "teams": {t: {k: an.clean(v) for k, v in s.items()} for t, s in sim_t.items()} if sim_ok else None},
            "draft": draft_order(ctx, recs, sim, seeds), "bracket": bracket(ctx, sim, seeds, cards), "ratings": ratings,
            "ratings_history_cols": ["week", "net", "off", "def"], "model_errors": dict(ctx.model_errors)}


def schedule(ctx: SeasonContext, prices: dict, frozen: dict, markets: dict | None, wf: dict | None = None) -> dict:
    from oddsmarkets.nfl.analytics import adapters
    from oddsmarkets.nfl.analytics import games as GM
    mk = (markets or {}).get("games") or {}
    cards = []
    for gid, g in sorted(ctx.games.items(), key=lambda kv: (int(kv[1].get("week") or 0), GTYPE_ORDER.get(kv[1].get("gtype"), 9),
                                                            str(kv[1].get("kickoff") or kv[1].get("date") or ""), kv[0])):
        pr = prices.get(gid) or frozen.get(gid) or (wf or {}).get(gid)
        c = GM.card(ctx, g, GM.model_block(pr), GM.market_block(g, mk.get(gid) if isinstance(mk, dict) else None))
        if str(g.get("status") or "").lower() in adapters.LIVE:
            rec = GM.espn_summary(g) or (g.get("live") if isinstance(g.get("live"), dict) else None)
            w = adapters.live_wp(ctx, g, rec, pr)
            if w:
                c["status"] = "live"
                c["wp_home"] = an.rnd(w.get("wp_home"), 4)
                c["wp_home_espn"] = an.rnd(w.get("espn_wp_home"), 4)
                c["wp_source"] = w.get("source")
        cards.append(c)
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "games": cards}


def weeks(ctx: SeasonContext, cards: list[dict], tms: dict | None) -> dict[int, dict]:
    """weeks/<w>.json: the week's games with model v market v line, edges and key unit matchups."""
    tt = (tms or {}).get("teams") or {}
    out: dict[int, dict] = {}
    for c in cards:
        w = an.inum(c.get("week"))
        if w is None:
            continue
        e = out.setdefault(w, {"ok": True, "season": ctx.season, "week": w, "updated_at": an.now(), "games": []})
        m, mk, ln = c.get("model") or {}, c.get("market") or {}, c.get("line") or {}
        from oddsmarkets.nfl.analytics.games import ml_prob
        p_line = ml_prob(ln.get("ml_home"), ln.get("ml_away"))
        edges = {"model_v_market": an.rnd(m.get("p_home") - mk["p_home"], 4) if m.get("p_home") is not None and mk.get("p_home") is not None else None,
                 "model_v_line": an.rnd(m.get("p_home") - p_line, 4) if m.get("p_home") is not None and p_line is not None else None,
                 "spread_v_line": an.rnd(m.get("spread") - ln["spread_home"], 1) if m.get("spread") is not None and ln.get("spread_home") is not None else None,
                 "total_v_line": an.rnd(m.get("total") - ln["total"], 1) if m.get("total") is not None and ln.get("total") is not None else None,
                 "p_home_line": an.rnd(p_line, 4)}
        e["games"].append({**c, "edges": edges, "matchup": matchup(tt.get(c.get("home")), tt.get(c.get("away")))})
    for w, e in out.items():
        e["gtypes"] = sorted({g.get("gtype") for g in e["games"]}, key=lambda x: GTYPE_ORDER.get(x, 9))
    return out


def matchup(h: dict | None, a: dict | None) -> dict | None:
    """Unit matchups: each offence against the other's defence (EPA per play, pass and rush) with league ranks."""
    if not h or not a:
        return None
    hv, av, hr, ar = h.get("values") or {}, a.get("values") or {}, h.get("rank") or {}, a.get("rank") or {}

    def side(o, orank, d, drank):
        return {"pass": {"off": o.get("off_pass_epa"), "off_rank": orank.get("off_pass_epa"), "def": d.get("def_pass_epa"),
                         "def_rank": drank.get("def_pass_epa")},
                "rush": {"off": o.get("off_rush_epa"), "off_rank": orank.get("off_rush_epa"), "def": d.get("def_rush_epa"),
                         "def_rank": drank.get("def_rush_epa")},
                "proe": o.get("proe_neutral"), "pace": o.get("sec_per_play_neutral")}
    return {"home_off": side(hv, hr, av, ar), "away_off": side(av, ar, hv, hr),
            "rating": {"home": hv.get("rating"), "away": av.get("rating")}, "st": {"home": hv.get("st_epa_g"), "away": av.get("st_epa_g")}}


def markets_payload(ctx: SeasonContext, sim: dict | None, awards: dict | None, cards: list[dict], markets: dict | None) -> dict:
    """markets.json: game prices (model v market v line), futures (SB, conferences, divisions, playoffs, 1 seed, win
    totals) and awards, each market price beside our probability with the edge."""
    mk = markets or {}
    sim_ok = bool((sim or {}).get("ok"))
    st = (sim or {}).get("teams") or {} if sim_ok else {}
    games = []
    for c in cards:
        if c.get("status") == "final":
            continue
        if c.get("market") or c.get("model"):
            m, k = c.get("model") or {}, c.get("market") or {}
            games.append({"game_id": c["game_id"], "week": c.get("week"), "home": c["home"], "away": c["away"], "kickoff": c.get("kickoff"),
                          "model": m or None, "market": k or None, "line": c.get("line"),
                          "edge": an.rnd(m.get("p_home") - k["p_home"], 4) if m.get("p_home") is not None and k.get("p_home") is not None else None})
    fut = mk.get("futures") or {}
    futures: dict[str, list] = {}

    def title(name: str, t: dict | None, key: str, teams: list[str] | None = None):
        probs = (t or {}).get("probs") or {}
        if not probs and not (t or {}).get("available"):
            if t is not None:
                futures[name] = []
            return
        ids = sorted(set(probs) | set(teams or []))
        rows = []
        for team in ids:
            q = an.fnum(probs.get(team))
            m = an.fnum((st.get(team) or {}).get(key)) if key else None
            rows.append({"team": team, "market": an.rnd(q, 4), "model": an.rnd(m, 4),
                         "edge": an.rnd(m - q, 4) if m is not None and q is not None else None})
        rows.sort(key=lambda e: -(e["market"] if e["market"] is not None else (e["model"] or 0)))
        futures[name] = rows
    if isinstance(fut, dict) and fut:
        title("sb", fut.get("champion"), "p_sb")
        for c in ("AFC", "NFC"):
            title(f"conf_{c.lower()}", (fut.get("conference") or {}).get(c), "p_conf",
                  [t for t, v in ctx.teams.items() if v.get("conference") == c])
            title(f"seed1_{c.lower()}", (fut.get("top_seed") or {}).get(c), "p_1seed",
                  [t for t, v in ctx.teams.items() if v.get("conference") == c])
        for d, t in (fut.get("division") or {}).items():
            title(f"div_{d.lower().replace(' ', '_')}", t, "p_div", [x for x, v in ctx.teams.items() if v.get("division") == d])
        title("playoffs", fut.get("playoffs"), "p_playoffs")
    win_totals = None
    wt_mk = (fut or {}).get("win_totals") if isinstance(fut, dict) else None
    if sim_ok or wt_mk:
        win_totals = {}
        for t in sorted(set(st) | set(wt_mk or {})):
            s_ = st.get(t) or {}
            wd = s_.get("win_dist") or []
            row = {"mean_wins": an.rnd(s_.get("mean_wins"), 2), "win_dist": wd}
            for src, v in ((wt_mk or {}).get(t) or {}).items():
                line, po = an.fnum((v or {}).get("line")), an.fnum((v or {}).get("p_over"))
                ours = None
                if line is not None and wd:
                    ours = sum(float(x) for i, x in enumerate(wd) if i > line)
                row[src] = {"line": line, "p_over": an.rnd(po, 4), "model_over": an.rnd(ours, 4),
                            "edge": an.rnd(ours - po, 4) if ours is not None and po is not None else None, "ladder": (v or {}).get("ladder")}
            win_totals[t] = row
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "games": games, "futures": futures, "win_totals": win_totals,
            "awards": (awards or {}).get("markets") if isinstance(awards, dict) else None, "fetched": bool(mk),
            "futures_error": (fut or {}).get("error") if isinstance(fut, dict) else None, "generated_at": (fut or {}).get("generated_at")
            if isinstance(fut, dict) else None,
            "sources": ["Kalshi", "Polymarket"], "notice": "18+. Prices are informational; no affiliation with any bookmaker or exchange."}


def gaps(cards: list[dict], futures: dict | None = None, n: int = 10) -> list[dict]:
    """Biggest model v market gaps among games not final (and futures when given)."""
    out = []
    for c in cards:
        m, k = c.get("model") or {}, c.get("market") or {}
        if c.get("status") != "final" and m.get("p_home") is not None and k.get("p_home") is not None:
            out.append({"game_id": c["game_id"], "model": m["p_home"], "market": k["p_home"], "edge": an.rnd(m["p_home"] - k["p_home"], 4)})
    for name, ents in (futures or {}).items():
        for e in ents:
            if e.get("edge") is not None:
                out.append({"name": f"{name}: {e['team']}", "model": e["model"], "market": e["market"], "edge": e["edge"]})
    out.sort(key=lambda x: -abs(x["edge"]))
    return out[:n]


def level_entry(ctx: SeasonContext) -> dict:
    return {"season": ctx.season, "week": ctx.week, "phase": ctx.phase}
