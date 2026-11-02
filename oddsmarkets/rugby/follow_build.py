"""The Quant Scrum's follow cards (My Teams): one small card per national side at data/follow/<scope>/<id>.json
(scope men | women), on the shared schema and fact engine in oddsmarkets/common/follow.py.

Built from the in-memory state of a scope's build (pages.build_scope), so it adds no fetching:
    team      name, abbreviation, kit colours, the route ("#/men/team/9"), "Men's tests"
    now       the record over the last 12 months, the form (last five), our rating and its rank
    chances   the title chance in each competition we simulate that the side is in
    next      up to three upcoming tests with our chance (frozen from the same walk the site shows)
    last      the last result with our pre-match chance and the upset flag
    profile   three strengths and two weaknesses (team-profile percentiles, opponent-adjusted)
    facts     the shared fact engine (streaks, rating moves, percentiles, the next big game ...)
    players   the side's two most valuable players on Scrum value (current window, qualified)

    build(result, data_root) -> {"n", "bytes", "max", "ids"}

No look-ahead: a result counts only when it is final before the build clock, a finished match's chance is the
walk-forward chance from before it, and the 7-day rating move compares the rating path on those two days.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from pathlib import Path

from oddsmarkets.common import follow as FL

from . import analytics as AN, build as B, config, players as PL

SITE, SPORT = config.SITE["slug"], config.SITE["sport"]
COMP_LABEL = {"six": "Six Nations", "trc": "Rugby Championship", "nc": "Nations Championship", "rwc": "World Cup"}


def _phase(S) -> str:
    if S.upcoming and S.upcoming[0]["date"] <= (S.now + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M"):
        return "season"
    if S.finals and S.finals[-1]["date"][:10] >= (S.now - timedelta(days=10)).date().isoformat():
        return "season"
    return "offseason"


def build(res: dict, data_root: Path) -> dict:
    S, w, rep, ana, prof, comps_out, ratings = (res[k] for k in ("S", "w", "rep", "ana", "prof", "comps", "ratings"))
    asof = S.now
    phase = _phase(S)
    rk = {t["id"]: t for t in ratings["teams"]}
    n_rated = ratings.get("n_ranked") or sum(1 for t in ratings["teams"] if t.get("rank"))
    label = config.SCOPES[S.scope]["label"]
    cards = {}
    for tid, t in res["info"]["teams"].items():
        if not t.get("active"):
            continue                          # a side with no test in ten years gets no card (and no team page)
        hist = w["hist"].get(tid) or []
        results = []
        for m in B.team_results(S, tid):
            home = m["home"]["id"] == tid
            us, th = (m["hs"], m["as"]) if home else (m["as"], m["hs"])
            f = w["fc"].get(m["id"]) or {}
            p = f.get("p_home") if home else f.get("p_away")
            results.append({"date": m["date"], "res": "W" if us > th else ("D" if us == th else "L"), "p": p,
                            "home": home, "margin": us - th})
        yr = [r for r in results if r["date"][:10] >= (S.now - timedelta(days=365)).date().isoformat()]
        wdl = Counter(r["res"] for r in yr)
        r = rk.get(tid)
        team = {"name": t["name"], "short": t["name"], "abbr": t.get("abbr"), "colour": t.get("colour"), "alt": t.get("alt"),
                "href": f"#/{S.scope}/team/{tid}", "league": label}
        now_blk = {"record": FL.record_text(wdl["W"], wdl["L"], wdl["D"] or None) if yr else None,
                   "form": FL.form_letters(results, asof, 5)}
        st = FL.streak_of(results, asof)
        if st and st[1] >= 2:
            now_blk["streak"] = f"{st[0]}{st[1]}"
        if r and r.get("rank"):
            now_blk["rating"] = {"value": r["rating"], "text": ("+" if r["rating"] >= 0 else "") + f"{r['rating']:.1f}",
                                 "rank": r["rank"], "of": n_rated, "label": "Our rating"}
            wr_txt = ""
            if r.get("wr_rank") and S.scope == "men":
                wr_txt = " · " + FL.ordinal(r["wr_rank"]) + " in World Rugby's (our rebuild)"
            now_blk["standing"] = {"pos": r["rank"], "of": n_rated, "text": FL.ordinal(r["rank"]) + " in our ratings" + wr_txt}
        elif r:
            # provisional: too few tests against the main pool to rank (pages.ratings_payload)
            now_blk["rating"] = {"value": r["rating"], "text": ("+" if r["rating"] >= 0 else "") + f"{r['rating']:.1f}",
                                 "label": "Our rating (provisional)"}
            if r.get("wr_rank") and S.scope == "men":
                now_blk["standing"] = {"pos": r["wr_rank"], "text": FL.ordinal(r["wr_rank"]) + " in World Rugby's (our rebuild)"}
        chances = []
        for key, c in comps_out.items():
            sim = (c.get("next") or {}).get("sim") or c.get("sim")
            if not sim:
                continue
            row = next((x for x in sim["teams"] if x["team"] == t["name"]), None)
            if row:
                p = row.get("title", row.get("champion"))
                if p is not None:
                    chances.append({"key": key, "label": COMP_LABEL.get(key, key), "p": round(p, 4), "d7": None})
        nxt = []
        for m in S.upcoming:
            if tid not in (m["home"]["id"], m["away"]["id"]):
                continue
            f = w["up"].get(m["id"]) or {}
            home = m["home"]["id"] == tid
            opp = m["away"] if home else m["home"]
            ot = S.teams.get(opp["id"]) or {}
            nxt.append({"id": m["id"], "start": m["date"], "home": home, "opp": {"name": ot.get("name"), "abbr": ot.get("abbr"), "colour": ot.get("colour")},
                        "comp": config.comp(m["slug"])["name"], "p": round(f["p_home"] if home else f["p_away"], 4) if f else None,
                        "p_draw": round(f["p_draw"], 4) if f else None, "href": f"#/{S.scope}/match/{m['id']}"})
            if len(nxt) >= 3:
                break
        last = None
        tr = B.team_results(S, tid)
        if tr:
            m = tr[-1]
            home = m["home"]["id"] == tid
            us, th = (m["hs"], m["as"]) if home else (m["as"], m["hs"])
            opp = m["away"] if home else m["home"]
            ot = S.teams.get(opp["id"]) or {}
            f = w["fc"].get(m["id"]) or {}
            p = f.get("p_home") if home else f.get("p_away")
            resl = "W" if us > th else ("D" if us == th else "L")
            last = {"id": m["id"], "start": m["date"], "home": home, "opp": {"name": ot.get("name"), "abbr": ot.get("abbr"), "colour": ot.get("colour")},
                    "score": [us, th], "res": resl, "p": round(p, 4) if p is not None else None,
                    "upset": FL.upset_flag(p, resl), "comp": config.comp(m["slug"])["name"], "href": f"#/{S.scope}/match/{m['id']}"}
        profile = None
        p = prof["teams"].get(tid)
        if p:
            sw = AN.strengths(p)
            labs = {i: l for i, l, *_ in AN.TEAM_METRICS}

            def txt(mid):
                v = p["m"][mid]["raw"]
                return f"{v * 100:.0f}%" if AN.TEAM_UNITS.get(mid) == "%" else f"{v:.1f} a test"
            profile = {"strong": [{"id": x["id"], "label": labs[x["id"]], "pct": x["pct"], "text": txt(x["id"])} for x in sw["best"]],
                       "weak": [{"id": x["id"], "label": labs[x["id"]], "pct": x["pct"], "text": txt(x["id"])} for x in sw["worst"][:2]]}
        pl = []
        for aid, rec in ana["players"].items():
            cur = rec.get("cur") or {}
            if not cur.get("qual"):
                continue
            g = [x for x in ana["games"][aid] if x["date"] >= ana["cur_from"]]
            if not g or Counter(x["team"] for x in g).most_common(1)[0][0] != tid:
                continue
            pl.append((cur["rates"]["val80"], aid, rec))
        pl.sort(key=lambda x: -x[0])
        players = [{"name": (S.athletes.get(aid) or {}).get("name") or aid, "pos": PL.POS_NAME.get(rec.get("pos") or "", ""),
                    "metric": "value per 80", "value": round(v, 2), "text": ("+" if v >= 0 else "") + f"{v:.1f}",
                    "href": f"#/{S.scope}/player/{aid}"} for v, aid, rec in pl[:2]]
        ctx = {"name": t["name"], "short": t["name"], "the": False, "phase": phase, "results": results,
               "rating": {"rank": r["rank"], "of": n_rated, "text": now_blk["rating"]["text"], "unit": "points"} if r and r.get("rank") else None,
               "league_name": label}
        if nxt:
            n0 = nxt[0]
            ctx["next"] = {"start": n0["start"], "opp": n0["opp"]["name"], "p": n0["p"]}
        try:
            fx = FL.facts(ctx, asof)
        except Exception:      # a fact template that does not fit rugby must never stop the card
            fx = []
        line = None
        if phase == "offseason" and tr:
            line = f"Last test: {last['res']} {last['score'][0]}{FL.DASH}{last['score'][1]} v {last['opp']['name']}." if last else None
        cards[tid] = FL.make_card(site=SITE, sport=SPORT, scope=S.scope, ident=tid, team=team, asof=asof, phase=phase,
                                  season=S.now.year, now=now_blk, chances=chances[:3], next_games=nxt,
                                  next_note=None if nxt else "No test scheduled yet.", last=last, line=line,
                                  profile=profile, facts=fx, players=players)
    return FL.write_cards(Path(data_root) / "follow", S.scope, cards)
