"""
prospects.json (each minor level): every player of the season with his line at the level (from its catalogues), his
MLB-equivalent rates and, for Triple-A, a call-up preview. Below Triple-A the translation chains one fitted step per
level (chain_translation).

MLB equivalents (builder D's translations): each component rate r of a player's AAA counts is moved by the
AAA -> MLB delta fitted on players with both samples in a season (logit for rates, linear for xwOBAcon;
projections.fit_translation, defaults when too few players): r_mlb = inverse(transform(r_aaa) + delta). The
equivalent wOBA recombines the translated events with the season's wOBA weights:
    wOBA_eq = (w_BB BB + w_HBP HBP + w_1B 1B + w_2B 2B + w_3B 3B + w_HR HR) / PA
with 1B = non-HR hits - extra-base hits, 2B = extra-base hits - triples (translated counts).
Call-up preview: builder D's next-season MLB projection (which already folds in the translated AAA counts at weight
0.6) and whether he has reached the majors this season.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics.context import SeasonContext

MIN_PA = 50


LADDER = ("a", "hia", "aa", "aaa", "mlb")


def chain_translation(PJ, level: str, seasons: list[int], role: str) -> tuple[dict, list[dict]]:
    """level -> MLB deltas: the sum of each adjacent step's fitted deltas (A -> A+ -> AA -> AAA -> MLB), each step
    fitted on players with both samples in a season and shrunk to the AAA -> MLB default; and the steps."""
    i = LADDER.index(level)
    total: dict[str, dict] = {}
    steps = []
    for lo, hi in zip(LADDER[i:-1], LADDER[i + 1:]):
        try:
            t = PJ.fit_translation(seasons, role, lo=lo, hi=hi)
        except Exception:                                        # noqa: BLE001
            t = {c: {"delta": v, "n": 0, "source": "default"} for c, v in PJ.TRANSLATE_DEFAULT[role].items()}
        steps.append({"from": lo, "to": hi, "deltas": t})
        for c, v in t.items():
            acc = total.setdefault(c, {"delta": 0.0, "n": int(v.get("n") or 0), "source": "fitted"})
            acc["delta"] += float(v.get("delta") or 0.0)
            acc["n"] = min(acc["n"], int(v.get("n") or 0))
            if v.get("source") != "fitted":
                acc["source"] = "default"
    return total, steps


def build(ctx: SeasonContext, aaa_hitters: dict | None, aaa_pitchers: dict | None, mlb_proj: dict | None = None,
          mlb_hitters: dict | None = None, mlb_pitchers: dict | None = None) -> dict:
    """The level's prospects (any minor level; the arguments keep their Triple-A names: the level's own catalogues)."""
    if ctx.level not in LADDER[:-1]:
        return {"ok": False, "reason": "prospects are built from the minor leagues", "level": ctx.level, "season": ctx.season}
    try:
        from oddsmarkets.baseball.models import projections as PJ
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "reason": f"projections unavailable: {exc}", "season": ctx.season}
    try:
        ah, ap = PJ.season_aggregates(ctx.level, ctx.season)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "reason": f"{ctx.level} aggregates: {exc}", "season": ctx.season}
    seasons = [s for s in range(ctx.season - 2, ctx.season + 1)]
    trans, steps = {}, {}
    for role in ("hitter", "pitcher"):
        trans[role], steps[role] = chain_translation(PJ, ctx.level, seasons, role)
    try:
        ww = PJ.woba_weights(ctx.season)
    except Exception:                                            # noqa: BLE001
        ww = PJ.WOBA_DEFAULT
    parents = {t: (v or {}).get("parent") for t, v in ctx.teams.items()}
    players: dict[str, dict] = {}
    for role, agg, cat, mcat, nkey in (("hitter", ah, aaa_hitters, mlb_hitters, "pa"), ("pitcher", ap, aaa_pitchers, mlb_pitchers, "bf")):
        if agg is None or not len(agg):
            continue
        eq = PJ._translate_counts(agg, role, trans[role])
        crow = (cat or {}).get("players") or {}
        mrow = (mcat or {}).get("players") or {}
        proj = ((mlb_proj or {}).get("hitters" if role == "hitter" else "pitchers")) or {}
        for pid, r in eq.iterrows():
            pid = str(pid)
            pa = float(r.get("PA") or 0)
            if pa < MIN_PA:
                continue
            e = {k: float(r.get(k) or 0) for k in ("K", "BB", "HBP", "HR", "NHHITS", "XBH", "3B", "XW_SUM", "XW_N", "PA", "GBALL", "BIP")}
            b1 = max(e["NHHITS"] - e["XBH"], 0.0)
            b2 = max(e["XBH"] - e["3B"], 0.0)
            woba_eq = (ww.get("BB", .69) * e["BB"] + ww.get("HBP", .72) * e["HBP"] + ww.get("1B", .88) * b1 + ww.get("2B", 1.25) * b2
                       + ww.get("3B", 1.58) * e["3B"] + ww.get("HR", 2.03) * e["HR"]) / pa
            mlb_eq = {"k_pct": an.rnd(e["K"] / pa, 3), "bb_pct": an.rnd(e["BB"] / pa, 3), "hr_pa": an.rnd(e["HR"] / pa, 4),
                      "xwobacon": an.rnd(an.div(e["XW_SUM"], e["XW_N"]), 3), "gb_pct": an.rnd(an.div(e["GBALL"], e["BIP"]), 3),
                      "woba": an.rnd(woba_eq, 3)}
            if mlb_eq["k_pct"] is not None and mlb_eq["bb_pct"] is not None:
                mlb_eq["k_bb_pct"] = round(mlb_eq["k_pct"] - mlb_eq["bb_pct"], 3)
            c = crow.get(pid) or {}
            v = c.get("values") or {}
            keys = (("pa", "avg", "obp", "slg", "woba", "xwoba_savant", "k_pct", "bb_pct", "hr", "barrel_pct", "ev", "chase_pct", "whiff_pct",
                     "bat_speed", "sprint_speed") if role == "hitter" else
                    ("ip", "bf", "ra9", "fip", "k_pct", "bb_pct", "k_bb_pct", "whiff_pct", "csw_pct", "fb_velo", "stuff_plus", "pitching_plus",
                     "gb_pct", "xwoba_savant"))
            pj = proj.get(pid) or {}
            team = c.get("team")
            players[pid] = {"name": c.get("name") or ctx.name(pid), "kind": role, "team": team, "parent": parents.get(str(team)) if team else None,
                            "pos": c.get("pos") or (ctx.players.get(pid) or {}).get("pos"), "age": c.get("age"),
                            "aaa": {k: v.get(k) for k in keys}, "aaa_pct": {k: (c.get("pct") or {}).get(k) for k in keys if (c.get("pct") or {}).get(k) is not None},
                            "mlb_eq": mlb_eq, "n": int(pa),
                            "mlb_proj": {"woba": pj.get("wOBA"), "rates": (pj.get("rates") or {}).get("all"), "components": pj.get("components"),
                                         "age": pj.get("age")} if pj else None,
                            "mlb_this_season": (mrow.get(pid) or {}).get(nkey),
                            # the MLB debut season (people.json): a debut this season with big-league time is a call-up
                            "debut": an.inum((ctx.people.get(pid) or {}).get("debut")) if isinstance(ctx.people, dict) else None}
    if not players:
        return {"ok": False, "reason": f"no {ctx.level} aggregates for this season", "level": ctx.level, "season": ctx.season}
    hit = sorted((p for p, r in players.items() if r["kind"] == "hitter" and r["n"] >= 100), key=lambda p: -(players[p]["mlb_eq"]["woba"] or 0))
    pit = sorted((p for p, r in players.items() if r["kind"] == "pitcher" and r["n"] >= 100),
                 key=lambda p: -(players[p]["mlb_eq"].get("k_bb_pct") or -1))
    for i, p in enumerate(hit):
        players[p]["rank"] = i + 1
    for i, p in enumerate(pit):
        players[p]["rank"] = i + 1
    # call-ups (round 9): Triple-A players this season whose major-league debut came this season, most big-league time first
    callups = sorted((p for p, r in players.items() if r.get("debut") == ctx.season and (r.get("mlb_this_season") or 0) > 0),
                     key=lambda p: -(players[p].get("mlb_this_season") or 0))
    return {"ok": True, "level": ctx.level, "season": ctx.season, "updated_at": an.now(), "players": players,
            "ranked": {"hitters": hit[:100], "pitchers": pit[:100]}, "callups": callups, "translation": an.clean(trans), "steps": an.clean(steps), "woba_weights": ww,
            "rules": {"min_pa": MIN_PA, "rank_min": 100}}
