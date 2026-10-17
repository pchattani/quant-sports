"""
season.json, the postseason bracket (SERIES), markets.json, schedule.json and the hub's index entries.

season.json: standings by division (W-L, run differential, Pythagorean and rating-expected W-L, playoff /
division / bye / World Series odds from builder D's simulation, magic numbers, seeds), team ratings (offence,
defence, pitching runs per game, teams.py), and the postseason bracket with series odds.

Expected W-L from our ratings: win% = (R + r/2)^1.83 / ((R + r/2)^1.83 + (R - r/2)^1.83), R the league's runs per
team-game and r the team's rating (expected run differential per game), times games played.

SERIES (PAYLOADS): {"id","round","teams":[tid,tid],"wins":[a,b],"best_of","p":[pa,pb],"market":[pa,pb]|null,
"games":[gpk...]} with teams[0] the team holding home field; p from the closed form with the game model's home and
away probabilities (builder D), the simulation's figure alongside.
"""
from __future__ import annotations

from typing import Any

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import catalog as CT
from oddsmarkets.baseball.analytics.context import SeasonContext

ROUND_NAME = {"WC": "Wild Card Series", "DS": "Division Series", "CS": "League Championship Series", "WS": "World Series"}
BEST_OF = {"WC": 3, "DS": 5, "CS": 7, "WS": 7}
GTYPE_ROUND = {"F": "WC", "D": "DS", "L": "CS", "W": "WS"}
ROUND_ORDER = ["WC", "DS", "CS", "WS"]


def series_list(ctx: SeasonContext, sim: dict | None, markets: dict | None) -> list[dict]:
    post = (sim or {}).get("postseason") or {}
    live = post.get("series") or []
    mk = {}
    for s in ((markets or {}).get("futures") or {}).get("series") or []:
        tms = [str(t) for t in (s.get("teams") or [])]
        if len(tms) == 2:
            mk[frozenset(tms)] = s
    games: dict[tuple, list] = {}
    for g in sorted(ctx.games.values(), key=lambda g: (str(g.get("date")), str(g.get("start") or ""))):
        rnd = GTYPE_ROUND.get(str(g.get("gtype")))
        if not rnd:
            continue
        key = (rnd, frozenset((str(g.get("home")), str(g.get("away")))))
        games.setdefault(key, []).append(str(g.get("gpk")))
    out = []
    for s in live:
        rnd = s.get("round")
        a, b = str(s.get("home_field")), str(s.get("other"))
        # the simulation's figure prices the next game with its probables (builder D's game model); the closed form uses
        # the pair matrix for every game. The simulation leads when it exists.
        pa = s.get("p_home_field_sim") if s.get("p_home_field_sim") is not None and not s.get("done") else s.get("p_home_field_closed_form")
        m = mk.get(frozenset((a, b)))
        mp = None
        if m and m.get("probs"):
            qa, qb = an.fnum(m["probs"].get(a)), an.fnum(m["probs"].get(b))
            if qa is not None or qb is not None:
                mp = [an.rnd(qa if qa is not None else 1 - qb, 4), an.rnd(qb if qb is not None else 1 - qa, 4)]
        gl = games.get((rnd, frozenset((a, b))), [])
        nxt = dict(s.get("next") or {}) or None
        if nxt is not None:
            ng = next((ctx.games.get(x) for x in gl if (ctx.games.get(x) or {}).get("status") not in ("final", "postponed", "cancelled")), None)
            nxt["gpk"] = str(ng.get("gpk")) if ng else None
            nxt["date"] = ng.get("date") if ng else None
            nxt["start"] = ng.get("start") if ng else None
        out.append({"id": f"{rnd}-{a}-{b}", "round": rnd, "round_name": ROUND_NAME.get(rnd), "teams": [a, b], "wins": s.get("wins"),
                    "best_of": BEST_OF.get(rnd), "p": [an.rnd(pa, 4), an.rnd(1 - pa, 4)] if pa is not None else None,
                    "p_sim": an.rnd(s.get("p_home_field_sim"), 4), "p_closed": an.rnd(s.get("p_home_field_closed_form"), 4),
                    "done": s.get("done"), "next": nxt,
                    "market": mp, "market_sources": (m or {}).get("sources"), "games": gl})
    return out


def current_round(series: list[dict]) -> str | None:
    live = [s["round"] for s in series if not s.get("done")]
    pool = live or [s["round"] for s in series]
    return max(pool, key=ROUND_ORDER.index) if pool else None


def build(ctx: SeasonContext, teams: dict | None, sim: dict | None, markets: dict | None = None) -> dict:
    from oddsmarkets.baseball.analytics.teams import records
    rec = records(ctx)
    tv = {t: r.get("values") or {} for t, r in ((teams or {}).get("teams") or {}).items()}
    sim = sim or {}
    reg = (sim.get("regular") or {}).get("teams") or {}
    post = sim.get("postseason") or {}
    pt = post.get("teams") or {}
    st = sim.get("standings") or {}
    meta_st = (ctx.store.get("meta") or {}).get("standings") or {}
    gp = [r["w"] + r["l"] for r in rec.values()]
    lg_rpg = (sum(r["rs"] for r in rec.values()) / max(sum(gp), 1)) if rec else 4.4
    divisions: dict[str, list] = {}
    for t in an.real_teams(ctx.store):
        info = an.team_info(ctx.store, t)
        r = rec.get(t) or {"w": 0, "l": 0, "rs": 0, "ra": 0}
        g = r["w"] + r["l"]
        v = tv.get(t) or {}
        rating = an.fnum(v.get("rating"))
        exp_pct = None
        if rating is not None and lg_rpg:
            a, b = max(lg_rpg + rating / 2, 0.1), max(lg_rpg - rating / 2, 0.1)
            exp_pct = a ** 1.83 / (a ** 1.83 + b ** 1.83)
        s = reg.get(t) or {}
        p = pt.get(t) or {}
        ss = st.get(t) or {}
        ms = meta_st.get(t) or {}
        row = {"tid": t, "name": info["name"], "abbr": info["abbr"], "short": info["short"], "league": info["league"],
               "division": info["division"], "w": r["w"], "l": r["l"], "pct": an.rnd(an.div(r["w"], g), 3), "gb": ss.get("gb", ms.get("gb")),
               "rs": r["rs"], "ra": r["ra"], "rd": r["rs"] - r["ra"],
               "pythag_w": an.rnd(v.get("pythag_w"), 1), "exp_w": an.rnd(exp_pct * g, 1) if exp_pct is not None else None,
               "exp_pct": an.rnd(exp_pct, 3), "rating": an.rnd(rating, 2), "off": v.get("off_rpg"), "def": v.get("def_rpg"),
               "pit": v.get("pit_rpg"), "seed": ss.get("seed"), "div_winner": ss.get("div_winner"),
               "clinched": ms.get("clinched"), "streak": _streak(ctx, t), "last10": _last10(ctx, t)}
        if s:
            row.update({k: s.get(k) for k in ("exp_w", "w_p05", "w_p95", "p_division", "p_wildcard", "p_bye", "p_postseason", "p_ds",
                                              "p_lcs", "p_pennant", "p_ws", "magic", "next", "seed_dist")})
            row["proj_w"] = s.get("exp_w")
            row["exp_w"] = an.rnd(exp_pct * g, 1) if exp_pct is not None else None
        elif p or ctx.phase in ("postseason", "offseason"):
            row.update({"p_postseason": 1.0 if p else 0.0, "p_ds": p.get("p_ds"), "p_lcs": p.get("p_lcs"), "p_pennant": p.get("p_pennant"),
                        "p_ws": p.get("p_ws"), "next": p.get("next")})
        divisions.setdefault(info["division"] or "-", []).append(row)
    for d in divisions.values():
        d.sort(key=lambda x: (-(x["pct"] or 0), -x["w"]))
    series = series_list(ctx, sim, markets)
    bracket = None
    if post.get("available"):
        bracket = {"round": current_round(series), "series": series, "seeds": post.get("seeds"),
                   "teams": {t: {**v, "name": an.team_info(ctx.store, t)["name"]} for t, v in pt.items()},
                   "matrix": post.get("matrix"), "sims": post.get("sims")}
    ratings = {t: {"off": v.get("off_rpg"), "def": v.get("def_rpg"), "pit": v.get("pit_rpg"), "total": v.get("rating")} for t, v in tv.items()}
    return {**CT.season_meta(ctx), "standings": divisions, "ratings": ratings, "league_rpg": an.rnd(lg_rpg, 3),
            "sim": {"available": bool(sim.get("available")), "basis": sim.get("basis"), "reason": sim.get("reason"),
                    "kind": "postseason" if post else ("regular" if sim.get("regular") else None),
                    "sims": (sim.get("regular") or post or {}).get("sims"), "remaining_games": (sim.get("regular") or {}).get("remaining_games")},
            "postseason": bracket, "next_games": sim.get("next_games")}


def _streak(ctx: SeasonContext, t: str) -> str | None:
    res = []
    for g in sorted(ctx.games.values(), key=lambda g: (str(g.get("date")), str(g.get("start") or ""))):
        if g.get("gtype") != "R" or g.get("status") != "final" or t not in (str(g.get("home")), str(g.get("away"))):
            continue
        rf, ra = (g["hs"], g["as"]) if str(g.get("home")) == t else (g["as"], g["hs"])
        res.append("W" if rf > ra else "L")
    if not res:
        return None
    k = 1
    while k < len(res) and res[-k - 1] == res[-1]:
        k += 1
    return f"{res[-1]}{k}"


def _last10(ctx: SeasonContext, t: str) -> str | None:
    res = []
    for g in sorted(ctx.games.values(), key=lambda g: (str(g.get("date")), str(g.get("start") or ""))):
        if g.get("gtype") != "R" or g.get("status") != "final" or t not in (str(g.get("home")), str(g.get("away"))):
            continue
        rf, ra = (g["hs"], g["as"]) if str(g.get("home")) == t else (g["as"], g["hs"])
        res.append(rf > ra)
    if not res:
        return None
    x = res[-10:]
    return f"{sum(x)}-{len(x) - sum(x)}"


def markets_payload(ctx: SeasonContext, sim: dict | None, awards: dict | None, prices: dict | None, series: list | None) -> dict:
    """markets.json: futures (World Series, pennants, awards) and series / game prices against the model, with edges
    (model / market - 1). Titles below the thin-market rule are published as unavailable."""
    mk = ctx.markets() or {}
    fut = mk.get("futures") or {}
    if not fut and not mk.get("games"):
        return {"ok": False, "reason": "markets not fetched this run (--no-market, light season or no network)", "level": ctx.level,
                "season": ctx.season}
    from oddsmarkets.baseball.sources import markets as MK
    sim = sim or {}
    tm = (sim.get("regular") or {}).get("teams") or (sim.get("postseason") or {}).get("teams") or {}
    out: dict[str, Any] = {"ok": True, "level": ctx.level, "season": ctx.season, "updated_at": an.now(), "generated_at": fut.get("generated_at")}
    out["champion"] = {"market": fut.get("champion"), "rows": MK.compare_titles({t: v.get("p_ws") for t, v in tm.items() if v.get("p_ws") is not None},
                                                                                fut.get("champion") or {})}
    out["pennant"] = {}
    for lg in ("AL", "NL"):
        model = {t: v.get("p_pennant") for t, v in tm.items() if v.get("p_pennant") is not None and (ctx.teams.get(t) or {}).get("league") == lg}
        out["pennant"][lg] = {"market": (fut.get("pennant") or {}).get(lg), "rows": MK.compare_titles(model, (fut.get("pennant") or {}).get(lg) or {})}
    out["awards"] = {}
    for k, title in (fut.get("awards") or {}).items():
        model = {r["pid"]: r["p"] for r in ((awards or {}).get(k) or {}).get("rows") or []}
        out["awards"][k] = {"market": title, "rows": MK.compare_titles(model, title or {})}
    out["advance"] = fut.get("advance")
    out["series"] = [{"id": s["id"], "round": s["round"], "teams": s["teams"], "wins": s.get("wins"), "next": s.get("next"),
                      "model": s["p"], "market": s["market"],
                      "edge": [MK.edge((s["p"] or [None, None])[i], (s["market"] or [None, None])[i]) for i in (0, 1)] if s.get("market") and s.get("p") else None}
                     for s in (series or [])]
    games = []
    for gpk, m in (mk.get("games") or {}).items():
        g = ctx.games.get(str(gpk)) or {}
        pm = (prices or {}).get(str(gpk)) or {}
        p_home = (pm.get("model") or {}).get("p_home") if pm else None
        games.append({"gpk": str(gpk), "date": g.get("date"), "home": str(g.get("home")), "away": str(g.get("away")), "model": p_home,
                      "market": m.get("p_home"), "basis": m.get("basis"), "sources": m.get("sources"), "total": m.get("total"),
                      "runline": m.get("runline"), "f5": m.get("f5"),
                      "edge": {"home": MK.edge(p_home, m.get("p_home")),
                               "away": MK.edge(1 - p_home if p_home is not None else None, 1 - m["p_home"] if m.get("p_home") is not None else None)}})
    out["games"] = sorted(games, key=lambda x: (str(x["date"]), x["gpk"]))
    return out


def level_entry(ctx: SeasonContext | None, seasons: list[int], teams: dict | None, sim: dict | None) -> dict:
    if ctx is None:
        return {"seasons": seasons}
    return {"season": ctx.season, "seasons": seasons, "phase": ctx.phase, "updated_at": an.now(), "teams": len(an.real_teams(ctx.store)),
            "games": len(ctx.games), "final": sum(1 for g in ctx.games.values() if (g or {}).get("status") == "final"),
            "sim": bool((sim or {}).get("available")), "has_pitches": ctx.has_pitches(), "model_errors": dict(ctx.model_errors)}
