"""
Teams catalogue (teams.json): about 80 metrics per team and season, plus each team's game log, roster and park.

Record and run differential from the store's final regular-season games; batting, pitching and discipline from
the pitch pass grouped by batting / fielding team; model metrics summed or weighted from the hitter and pitcher
catalogues (xwOBA+, Stuff+, Pitching+, decision value, Bullpen WAR) and builder C's fielding and framing.

Team ratings (runs per game above an average team, also in season.json):
    offence  = (batting runs + baserunning runs of the team's hitters) / games
    defence  = (fielding runs + framing runs) / games
    pitching = sum over its pitchers of (league RA9 x IP / 9 - expected runs from xwOBA+ against) / games
    total    = offence + defence + pitching (an expected run differential per game)
Pythagorean win% = RS^1.83 / (RS^1.83 + RA^1.83).
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import catalog as CT
from oddsmarkets.baseball.analytics.context import SeasonContext

M = an.metric
PYTH = 1.83

METRICS = [
    M("g", "G", "Record", "int", desc="Regular-season games played."),
    M("w", "W", "Record", "int", desc="Wins."),
    M("l", "L", "Record", "int", lower=True, desc="Losses."),
    M("pct", "Win%", "Record", "3", desc="W / (W + L)."),
    M("rs", "Runs scored", "Record", "int", desc="Runs scored."),
    M("ra", "Runs allowed", "Record", "int", lower=True, desc="Runs allowed."),
    M("rd", "Run differential", "Record", "int", desc="RS - RA."),
    M("pythag", "Pythagorean win%", "Record", "3", desc="RS^1.83 / (RS^1.83 + RA^1.83)."),
    M("pythag_w", "Pythagorean wins", "Record", "1", desc="Pythagorean win% x games."),
    M("luck", "Wins over Pythagorean", "Record", "1", desc="W minus Pythagorean wins."),
    M("baseruns_rs", "BaseRuns scored", "Record", "1",
      desc="Runs the team's batting events were worth by BaseRuns (A x B / (B + C) + HR), whatever order they came in; "
      "scaled so the league's BaseRuns equal its runs."),
    M("baseruns_ra", "BaseRuns allowed", "Record", "1", lower=True, desc="BaseRuns of the events the team's pitchers allowed (same scale)."),
    M("baseruns_pct", "BaseRuns win%", "Record", "3",
      desc="BaseRuns scored^1.83 / (scored^1.83 + allowed^1.83): the record the team's events deserved, with sequencing removed. "
      "Predicts second-half win% better than Pythagorean or actual win% (MLB 2015-2026)."),
    M("baseruns_w", "BaseRuns wins", "Record", "1", desc="BaseRuns win% x games."),
    M("home_pct", "Home win%", "Record", "3", desc="Win% at home."),
    M("away_pct", "Road win%", "Record", "3", desc="Win% on the road."),
    M("one_run_pct", "One-run win%", "Record", "3", desc="Win% in one-run games."),
    M("rating", "Rating (runs/game)", "Ratings", "2", scope="model", desc="Offence + defence + pitching ratings."),
    M("off_rpg", "Offence (runs/game)", "Ratings", "2", scope="model", desc="Batting plus baserunning runs above average per game."),
    M("def_rpg", "Defence (runs/game)", "Ratings", "2", scope="model", desc="Fielding plus framing runs per game."),
    M("pit_rpg", "Pitching (runs/game)", "Ratings", "2", scope="model", desc="Expected runs saved by the pitchers per game."),
    # batting
    M("avg", "AVG", "Batting", "3", desc="Team batting average."),
    M("obp", "OBP", "Batting", "3", desc="On-base percentage."),
    M("slg", "SLG", "Batting", "3", desc="Slugging."),
    M("ops", "OPS", "Batting", "3", desc="OBP + SLG."),
    M("iso", "ISO", "Batting", "3", desc="Isolated power."),
    M("woba", "wOBA", "Batting", "3", desc="Team wOBA."),
    M("xwoba_savant", "xwOBA (Savant)", "Batting", "3", scope="statcast", desc="Savant xwOBA."),
    M("xwoba_plus", "xwOBA+ (ours)", "Batting", "3", scope="model", desc="Our xwOBA, PA-weighted over the team's hitters."),
    M("k_pct", "K%", "Batting", "pct", lower=True, desc="Strikeouts per PA."),
    M("bb_pct", "BB%", "Batting", "pct", desc="Walks per PA."),
    M("hr", "HR", "Batting", "int", desc="Home runs."),
    M("barrel_pct", "Barrel%", "Batting", "pct", scope="statcast", desc="Barrels per ball in play."),
    M("hard_pct", "Hard-hit%", "Batting", "pct", scope="statcast", desc="95+ mph balls in play."),
    M("ev", "Exit velocity", "Batting", "mph", scope="statcast", desc="Mean exit velocity."),
    M("chase_pct", "Chase%", "Batting", "pct", lower=True, scope="statcast", desc="Swings outside the zone."),
    M("whiff_pct", "Whiff%", "Batting", "pct", lower=True, scope="statcast", desc="Whiffs per swing."),
    M("pull_air_pct", "Pull-air%", "Batting", "pct", scope="statcast", desc="Pulled line drives and fly balls."),
    M("bat_speed", "Bat speed", "Batting", "mph", scope="tracking", desc="Mean bat speed."),
    M("rv100", "Batting RV/100", "Batting", "2", scope="statcast", desc="Batting run value per 100 pitches."),
    M("dv", "Decision value", "Batting", "rv", scope="model", desc="Sum of the hitters' decision value (runs)."),
    M("bsr", "Baserunning runs", "Batting", "1", scope="model", desc="Sum of the hitters' baserunning runs."),
    M("wpa_bat", "Batting WPA", "Batting", "2", scope="model", desc="Win probability added by the hitters."),
    # pitching
    M("ra9", "RA9", "Pitching", "2", lower=True, desc="Runs allowed per nine."),
    M("fip", "FIP", "Pitching", "2", lower=True, desc="FIP (RA9 scale)."),
    M("p_k_pct", "K% (pitching)", "Pitching", "pct", desc="Strikeouts per batter faced."),
    M("p_bb_pct", "BB% (pitching)", "Pitching", "pct", lower=True, desc="Walks per batter faced."),
    M("p_k_bb", "K-BB%", "Pitching", "pct", desc="K% - BB%."),
    M("hr9", "HR/9", "Pitching", "2", lower=True, desc="Home runs per nine."),
    M("whip", "WHIP", "Pitching", "2", lower=True, desc="Walks plus hits per inning."),
    M("woba_against", "wOBA against", "Pitching", "3", lower=True, desc="wOBA allowed."),
    M("xwoba_against", "xwOBA against (Savant)", "Pitching", "3", lower=True, scope="statcast", desc="Savant xwOBA allowed."),
    M("xwoba_plus_against", "xwOBA+ against (ours)", "Pitching", "3", lower=True, scope="model", desc="Our xwOBA allowed (BF-weighted)."),
    M("stuff_plus", "Stuff+", "Pitching", "plus", scope="model", desc="Pitch-weighted Stuff+."),
    M("location_plus", "Location+", "Pitching", "plus", scope="model", desc="Pitch-weighted Location+."),
    M("pitching_plus", "Pitching+", "Pitching", "plus", scope="model", desc="Pitch-weighted Pitching+."),
    M("csw_pct", "CSW%", "Pitching", "pct", scope="statcast", desc="Called strikes plus whiffs per pitch."),
    M("p_chase_pct", "Chase% induced", "Pitching", "pct", scope="statcast", desc="Chase rate induced."),
    M("p_whiff_pct", "Whiff% induced", "Pitching", "pct", scope="statcast", desc="Whiffs per swing induced."),
    M("p_gb_pct", "GB% allowed", "Pitching", "pct", scope="statcast", desc="Ground-ball rate."),
    M("p_barrel_pct", "Barrel% allowed", "Pitching", "pct", lower=True, scope="statcast", desc="Barrels allowed per ball in play."),
    M("p_hard_pct", "Hard-hit% allowed", "Pitching", "pct", lower=True, scope="statcast", desc="Hard-hit rate allowed."),
    M("p_ev", "EV allowed", "Pitching", "mph", lower=True, scope="statcast", desc="Exit velocity allowed."),
    M("fb_velo", "Fastball velo", "Pitching", "mph", scope="statcast", desc="Mean fastball velocity."),
    M("sp_ra9", "Rotation RA9", "Pitching", "2", lower=True, desc="RA9 of starters."),
    M("rp_ra9", "Bullpen RA9", "Pitching", "2", lower=True, desc="RA9 of relievers."),
    M("sp_ip_share", "Rotation IP share", "Pitching", "pct", desc="Share of innings by starters."),
    M("p_rv100", "Pitching RV/100", "Pitching", "2", lower=True, scope="statcast", desc="Run value allowed per 100 pitches (batting side)."),
    M("wpa_pit", "Pitching WPA", "Pitching", "2", scope="model", desc="Win probability added by the pitchers."),
    # defence
    M("oaa", "OAA", "Defence", "1", scope="model", desc="Team outs above average (our model)."),
    M("fielding_runs", "Fielding runs", "Defence", "1", scope="model", desc="Team fielding runs."),
    M("framing_runs", "Framing runs", "Defence", "1", scope="model", desc="Catchers' framing runs."),
    M("oaa_savant", "Savant OAA", "Defence", "int", scope="statcast", desc="Sum of Savant OAA of the team's fielders."),
    # value
    M("war_bat", "Position-player WAR", "Value", "war", scope="model", desc="Sum of Bullpen WAR of the hitters."),
    M("war_pit", "Pitcher WAR", "Value", "war", scope="model", desc="Sum of RA9-based Bullpen WAR of the pitchers."),
    M("war_sp", "Rotation WAR", "Value", "war", scope="model", desc="Starters' WAR."),
    M("war_rp", "Bullpen WAR", "Value", "war", scope="model", desc="Relievers' WAR."),
    M("war", "Total WAR", "Value", "war", scope="model", desc="Position players plus pitchers."),
    M("age_bat", "Hitter age", "Value", "1", desc="PA-weighted age of the hitters."),
    M("age_pit", "Pitcher age", "Value", "1", desc="BF-weighted age of the pitchers."),
    # simulation
    M("p_postseason", "Postseason chance", "Simulation", "prob", scope="model", desc="Probability of reaching the postseason (season simulation)."),
    M("p_ws", "World Series chance", "Simulation", "prob", scope="model", desc="Probability of winning the World Series."),
]


def records(ctx: SeasonContext) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for g in ctx.games.values():
        if (g or {}).get("gtype") != "R" or g.get("status") != "final" or g.get("hs") is None or g.get("as") is None:
            continue
        h, a = str(g["home"]), str(g["away"])
        hs, as_ = int(g["hs"]), int(g["as"])
        for t, rs, ra, home in ((h, hs, as_, True), (a, as_, hs, False)):
            r = out.setdefault(t, {"w": 0, "l": 0, "rs": 0, "ra": 0, "hw": 0, "hl": 0, "aw": 0, "al": 0, "w1": 0, "l1": 0})
            win = rs > ra
            r["w" if win else "l"] += 1
            r["rs"] += rs
            r["ra"] += ra
            r[("h" if home else "a") + ("w" if win else "l")] += 1
            if abs(rs - ra) == 1:
                r["w1" if win else "l1"] += 1
    return out


def build(ctx: SeasonContext, hitters: dict | None, pitchers: dict | None, sim: dict | None = None, cards: list | None = None) -> dict:
    A = ctx.agg()
    bt, ft = (A or {}).get("bat_team"), (A or {}).get("fld_team")
    teams = an.real_teams(ctx.store)
    if not teams:
        return {"ok": False, "reason": "no teams in the store", "level": ctx.level, "season": ctx.season}
    rec = records(ctx)
    hp = ((hitters or {}).get("players") or {})
    pp = ((pitchers or {}).get("players") or {})
    t2a = {t: (ctx.teams.get(t) or {}).get("abbr") for t in teams}
    a2t_local = {}
    for ab, t in ctx.a2t.items():
        a2t_local.setdefault(t, set()).add(ab)
    fld_sv = CT.leaderboard("outs_above_average", ctx.season)
    cp_t = CT.lookup((ctx.model("catchprob").get("teams")), "team")
    sim_t = _sim_teams(sim)
    card_of = {str(c.get("gpk")): c for c in (cards or [])}
    align = alignment(ctx)
    pens = bullpens(ctx, t2a)
    lg_runs = sum(r["ra"] for r in rec.values())
    lg_ip = 0.0
    for r in pp.values():
        lg_ip += float(r["values"].get("ip") or 0)
    lg_ra9 = 9 * lg_runs / lg_ip if lg_ip else 4.4
    rows: dict[str, dict] = {}
    raw_bsr: dict[str, tuple] = {}
    for t in teams:
        v: dict[str, Any] = {}
        r = rec.get(t) or {}
        w, l = r.get("w", 0), r.get("l", 0)
        g = w + l
        v.update(g=g, w=w, l=l, pct=an.div(w, g), rs=r.get("rs"), ra=r.get("ra"))
        if g:
            v["rd"] = r["rs"] - r["ra"]
            if r["rs"] + r["ra"]:
                v["pythag"] = r["rs"] ** PYTH / (r["rs"] ** PYTH + r["ra"] ** PYTH)
                v["pythag_w"] = v["pythag"] * g
                v["luck"] = w - v["pythag_w"]
            v["home_pct"] = an.div(r["hw"], r["hw"] + r["hl"])
            v["away_pct"] = an.div(r["aw"], r["aw"] + r["al"])
            v["one_run_pct"] = an.div(r["w1"], r["w1"] + r["l1"])
        abbrs = a2t_local.get(t, {t2a.get(t)})
        b = _sum_rows(bt, abbrs)
        f = _sum_rows(ft, abbrs)
        if b is not None:
            bbs = b["bb"] + b["ibb"]
            v["avg"] = an.div(b["h"], b["ab"])
            v["obp"] = an.div(b["h"] + bbs + b["hbp"], b["ab"] + bbs + b["hbp"] + b["sf"])
            v["slg"] = an.div(b["tb"], b["ab"])
            if v["obp"] is not None and v["slg"] is not None:
                v["ops"] = v["obp"] + v["slg"]
                v["iso"] = v["slg"] - v["avg"]
            v["woba"] = an.div(b["w_num"], b["w_den"])
            v["xwoba_savant"] = an.div(b["xw_num"], b["w_den"])
            v["k_pct"] = an.div(b["k"], b["pa"])
            v["bb_pct"] = an.div(bbs, b["pa"])
            v["hr"] = b["hr"]
            v["barrel_pct"] = an.div(b["barrel"], b["lsa_n"])
            v["hard_pct"] = an.div(b["hard"], b["ev_n"])
            v["ev"] = an.div(b["ev_sum"], b["ev_n"])
            v["chase_pct"] = an.div(b["o_swing"], b["out_zone"])
            v["whiff_pct"] = an.div(b["whiff"], b["swing"])
            v["pull_air_pct"] = an.div(b["pull_air"], b["spray_n"])
            v["bat_speed"] = an.div(b["bs_sum"], b["bs_n"])
            v["rv100"] = 100 * b["rv"] / b["pitches"] if b["pitches"] else None
        if b is not None and f is not None and g:
            raw_bsr[t] = (_baseruns(b), _baseruns(f), g, (r.get("rs") or 0) + (r.get("ra") or 0))
        if f is not None:
            bbs = f["bb"] + f["ibb"]
            v["p_k_pct"] = an.div(f["k"], f["pa"])
            v["p_bb_pct"] = an.div(bbs, f["pa"])
            if v["p_k_pct"] is not None and v["p_bb_pct"] is not None:
                v["p_k_bb"] = v["p_k_pct"] - v["p_bb_pct"]
            v["woba_against"] = an.div(f["w_num"], f["w_den"])
            v["xwoba_against"] = an.div(f["xw_num"], f["w_den"])
            v["csw_pct"] = an.div(f["csw"], f["pitches"])
            v["p_chase_pct"] = an.div(f["o_swing"], f["out_zone"])
            v["p_whiff_pct"] = an.div(f["whiff"], f["swing"])
            v["p_gb_pct"] = an.div(f["gb"], f["bbt_n"])
            v["p_barrel_pct"] = an.div(f["barrel"], f["lsa_n"])
            v["p_hard_pct"] = an.div(f["hard"], f["ev_n"])
            v["p_ev"] = an.div(f["ev_sum"], f["ev_n"])
            v["fb_velo"] = None
            v["p_rv100"] = 100 * f["rv"] / f["pitches"] if f["pitches"] else None
        # from the player catalogues
        mine_h = {p: x for p, x in hp.items() if x.get("team") == t}
        mine_p = {p: x for p, x in pp.items() if x.get("team") == t}
        v["xwoba_plus"] = _wmean(mine_h, "xwoba_plus", "pa")
        v["dv"] = _sum(mine_h, "dv")
        v["bsr"] = _sum(mine_h, "bsr")
        v["wpa_bat"] = _sum(mine_h, "wpa")
        v["war_bat"] = _sum(mine_h, "war")
        v["age_bat"] = _wmean(mine_h, None, "pa", attr="age")
        v["xwoba_plus_against"] = _wmean(mine_p, "xwoba_plus", "bf")
        v["stuff_plus"] = _wmean(mine_p, "stuff_plus", "pitches")
        v["location_plus"] = _wmean(mine_p, "location_plus", "pitches")
        v["pitching_plus"] = _wmean(mine_p, "pitching_plus", "pitches")
        v["fb_velo"] = _wmean(mine_p, "fb_velo", "pitches")
        v["wpa_pit"] = _sum(mine_p, "wpa")
        v["war_pit"] = _sum(mine_p, "war")
        v["war_sp"] = _sum({p: x for p, x in mine_p.items() if x.get("role") == "SP"}, "war")
        v["war_rp"] = _sum({p: x for p, x in mine_p.items() if x.get("role") == "RP"}, "war")
        if v["war_bat"] is not None or v["war_pit"] is not None:
            v["war"] = (v["war_bat"] or 0) + (v["war_pit"] or 0)
        v["age_pit"] = _wmean(mine_p, None, "bf", attr="age")
        ip = sum(float(x["values"].get("ip") or 0) for x in mine_p.values())
        runs = sum(float(x["values"].get("r") or 0) for x in mine_p.values())
        hr = sum(float(x["values"].get("hr") or 0) for x in mine_p.values())
        bbh = sum(float((x["values"].get("bb") or 0) + (x["values"].get("ibb") or 0) + (x["values"].get("h") or 0)) for x in mine_p.values())
        if ip:
            v["ra9"] = 9 * runs / ip
            v["hr9"] = 9 * hr / ip
            v["whip"] = bbh / ip
            fips = [(float(x["values"].get("fip") or 0), float(x["values"].get("ip") or 0)) for x in mine_p.values() if x["values"].get("fip") is not None]
            if fips:
                v["fip"] = sum(a * b for a, b in fips) / max(sum(b for _, b in fips), 1e-9)
            for role, key in (("SP", "sp_ra9"), ("RP", "rp_ra9")):
                rip = sum(float(x["values"].get("ip") or 0) for x in mine_p.values() if x.get("role") == role)
                rr = sum(float(x["values"].get("r") or 0) for x in mine_p.values() if x.get("role") == role)
                v[key] = 9 * rr / rip if rip else None
                if role == "SP":
                    v["sp_ip_share"] = rip / ip
        # defence
        ct = cp_t.get(str(t2a.get(t))) or next((cp_t.get(a) for a in abbrs if a in cp_t), None) or {}
        v["oaa"] = CT.g(ct, "oaa")
        v["fielding_runs"] = CT.g(ct, "runs")
        v["framing_runs"] = _sum(mine_h, "framing_runs")
        sv = [CT.g(fld_sv.get(p), "outs_above_average") for p in mine_h]
        sv = [x for x in sv if x is not None]
        v["oaa_savant"] = sum(sv) if sv else None
        # ratings
        if g:
            off = (_sum(mine_h, "batting_runs") or 0) + (v["bsr"] or 0)
            dfn = (v["fielding_runs"] or 0) + (v["framing_runs"] or 0)
            pit = 0.0
            for x in mine_p.values():
                xr, ipp = x["values"].get("xra9"), x["values"].get("ip")
                if xr is not None and ipp:
                    pit += (lg_ra9 - xr) * ipp / 9
            v["off_rpg"], v["def_rpg"], v["pit_rpg"] = off / g, dfn / g, pit / g
            v["rating"] = v["off_rpg"] + v["def_rpg"] + v["pit_rpg"]
        s = sim_t.get(t) or {}
        v["p_postseason"] = s.get("p_postseason")
        v["p_ws"] = s.get("p_ws")
        info = an.team_info(ctx.store, t)
        rows[t] = {**info, "values": v, "log": game_log(ctx, t, card_of), "roster": roster(ctx, t, hp, pp), "park": info.get("venue"),
                   "bullpen": pens.get(t), "defence": align.get(t)}
    # BaseRuns standings: scale both sides so the league's BaseRuns equal its runs, then a Pythagorean record
    tot_b = sum(x[0] + x[1] for x in raw_bsr.values())
    tot_r = sum(x[3] for x in raw_bsr.values())
    mult = tot_r / tot_b if tot_b > 0 and tot_r > 0 else 1.0
    for t, (bs, ba, g, _) in raw_bsr.items():
        if t not in rows or bs <= 0 or ba <= 0:
            continue
        v = rows[t]["values"]
        v["baseruns_rs"], v["baseruns_ra"] = bs * mult, ba * mult
        v["baseruns_pct"] = bs ** PYTH / (bs ** PYTH + ba ** PYTH)
        v["baseruns_w"] = v["baseruns_pct"] * g
    pct = {}
    for m in METRICS:
        pc = an.percentiles({t: r["values"].get(m["key"]) for t, r in rows.items()}, m["lower"])
        for t, p in pc.items():
            pct.setdefault(t, {})[m["key"]] = p
    for t, r in rows.items():
        r["values"] = an.round_values(r["values"], METRICS)
        r["pct"] = pct.get(t, {})
    return {**CT.season_meta(ctx), "kind": "team", "metrics": [an.public_metric(m) for m in METRICS], "teams": rows,
            "constants": {"pythag_exponent": PYTH, "lg_ra9": round(lg_ra9, 3)}}


def _baseruns(x: pd.Series) -> float:
    """BaseRuns (Smyth) from a batting or pitching-allowed aggregate row: A x B / (B + C) + D with A = H + BB + IBB + HBP
    - HR, B = (1.4 TB - 0.6 H - 3 HR + 0.1 (BB + IBB + HBP)) x 1.02, C = AB - H, D = HR. 0 when it cannot be formed."""
    try:
        h, hr, tb, ab = float(x["h"]), float(x["hr"]), float(x["tb"]), float(x["ab"])
        walks = float(x["bb"]) + float(x["ibb"]) + float(x["hbp"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    a = h + walks - hr
    b = (1.4 * tb - 0.6 * h - 3.0 * hr + 0.1 * walks) * 1.02
    c = ab - h
    if not np.isfinite(a + b + c) or b + c <= 0:
        return 0.0
    return max(a * b / (b + c) + hr, 0.0)


def _sum_rows(tab: pd.DataFrame | None, abbrs) -> pd.Series | None:
    if tab is None or not len(tab):
        return None
    keys = [a for a in abbrs if a and a in tab.index]
    if not keys:
        return None
    return tab.loc[keys].sum()


def _sum(rows: dict, key: str) -> float | None:
    xs = [an.fnum(r["values"].get(key)) for r in rows.values()]
    xs = [x for x in xs if x is not None]
    return sum(xs) if xs else None


def _wmean(rows: dict, key: str | None, wkey: str, attr: str | None = None) -> float | None:
    num = den = 0.0
    for r in rows.values():
        x = an.fnum(r.get(attr) if attr else r["values"].get(key))
        w = an.fnum((r.get("n") or {}).get(wkey)) or an.fnum(r.get(wkey))
        if x is None or not w:
            continue
        num += x * w
        den += w
    return num / den if den else None


def _sim_teams(sim: dict | None) -> dict:
    s = sim or {}
    if s.get("regular"):
        return (s["regular"] or {}).get("teams") or {}
    post = (s.get("postseason") or {}).get("teams") or {}
    out = {}
    for t, r in (s.get("standings") or {}).items():
        out[t] = {"p_postseason": 1.0 if t in post else 0.0, "p_ws": (post.get(t) or {}).get("p_ws", 0.0)}
    return out


def game_log(ctx: SeasonContext, tid: str, card_of: dict | None = None) -> list:
    """[[gpk, date, gtype, opp, home(1/0), runs for, runs against, "W"|"L"|status, model p(win), market p(win)], ...] in date
    order; the probabilities are the team's side of the schedule card's model and market prices."""
    out = []
    for g in sorted(ctx.games.values(), key=lambda g: (str(g.get("date")), str(g.get("start") or ""), str(g.get("gpk")))):
        h, a = str(g.get("home")), str(g.get("away"))
        if tid not in (h, a) or g.get("gtype") not in ("R", "F", "D", "L", "W", "C"):
            continue
        home = tid == h
        rf, ra = (g.get("hs"), g.get("as")) if home else (g.get("as"), g.get("hs"))
        res = g.get("status")
        if g.get("status") == "final" and rf is not None and ra is not None:
            res = "W" if rf > ra else "L"
        c = (card_of or {}).get(str(g.get("gpk"))) or {}
        mp = an.fnum((c.get("model") or {}).get("p_home"))
        kp = an.fnum((c.get("market") or {}).get("p_home"))
        out.append([str(g.get("gpk")), g.get("date"), g.get("gtype"), a if home else h, int(home), rf, ra, res,
                    an.rnd(mp if home else 1 - mp, 4) if mp is not None else None, an.rnd(kp if home else 1 - kp, 4) if kp is not None else None])
    return out


def alignment(ctx: SeasonContext) -> dict[str, dict]:
    """Defensive alignment tendencies per fielding team: share of pitches with each infield / outfield alignment (Savant's
    if_fielding_alignment, of_fielding_alignment), overall and by batter hand."""
    from oddsmarkets.baseball.analytics import pitchagg as PG
    if not ctx.has_pitches():
        return {}
    cols = ["game_pk", "at_bat_number", "pitch_number", "batter", "pitcher", "game_type", "inning_topbot", "home_team", "away_team",
            "stand", "if_fielding_alignment", "of_fielding_alignment"]
    df = PG.load(ctx.level, ctx.season, cols, PG.REGULAR)
    if not len(df):
        return {}
    fld = PG.team_of(df, "fld")
    st = PG._s(df, "stand")
    out: dict[str, dict] = {}
    for kind, col in (("if", "if_fielding_alignment"), ("of", "of_fielding_alignment")):
        a = PG._s(df, col)
        ok = a != ""
        d = pd.DataFrame({"t": fld[ok].to_numpy(), "a": a[ok].to_numpy(), "s": st[ok].to_numpy()})
        if not len(d):
            continue
        for (t, s_), x in d.groupby(["t", "s"]):
            tid = ctx.tid(t)
            if tid is None:
                continue
            out.setdefault(tid, {}).setdefault(f"{kind}_by_stand", {})[s_] = {k: round(float(v), 4) for k, v in x["a"].value_counts(normalize=True).items()}
        for t, x in d.groupby("t"):
            tid = ctx.tid(t)
            if tid is None:
                continue
            out.setdefault(tid, {})[kind] = {k: round(float(v), 4) for k, v in x["a"].value_counts(normalize=True).items()}
    return out


def bullpens(ctx: SeasonContext, t2a: dict) -> dict[str, list]:
    """Current season only: each team's relievers (builder D's usage log) [{pid, name, throws, available, pitches_3d, rest,
    bf_30d}] as of today: available = 1 / 0.5 / 0 (out after 30+ pitches yesterday or two days running; half after pitching
    yesterday), rest = days since his last appearance."""
    if not ctx.current or not ctx.full:
        return {}
    gc = ctx.game_ctx()
    if gc is None:
        return {}
    from datetime import timedelta as _td
    out: dict[str, list] = {}
    today = ctx.today
    apps = gc.usage.apps
    lo3 = (today - _td(days=3)).isoformat()
    for t, ab in t2a.items():
        try:
            bp = gc.usage.bullpen(gc.tid_to_abbr.get(t, ab), today)
        except Exception:                                        # noqa: BLE001
            continue
        if bp is None or not len(bp):
            continue
        a = apps[apps["team"] == gc.tid_to_abbr.get(t, ab)] if len(apps) else apps
        rows = []
        for r in bp.to_dict("records"):
            pid = str(r["pitcher"])
            mine = a[a["pitcher"].astype(str) == pid] if len(a) else a
            last = max(mine["date"]) if len(mine) else None
            p3 = float(mine.loc[(mine["date"] >= lo3) & (mine["date"] < today.isoformat()), "pitches"].astype(float).sum()) if len(mine) else 0.0
            rest = (today - date.fromisoformat(str(last)[:10])).days if last else None
            rows.append({"pid": pid, "name": ctx.name(pid), "throws": r.get("throws"), "available": an.rnd(r.get("avail"), 2),
                         "pitches_3d": int(p3), "rest": rest, "bf_30d": an.inum(r.get("bf"))})
        rows.sort(key=lambda x: (-(x["available"] or 0), x["rest"] if x["rest"] is not None else 99))
        out[t] = rows
    return out


# extra roster columns (Bullpen redesign): next season's projected wOBA, platoon wOBA; starts, expected RA9, Pitching+,
# pitches per start
ROSTER_H = ("proj_woba", "woba_vl", "woba_vr")
ROSTER_P = ("proj_woba", "gs", "xra9", "pitching_plus", "p_start")


def roster(ctx: SeasonContext, tid: str, hp: dict, pp: dict) -> list:
    """[{pid, name, pos, kind, war, key stat}] for the team's players this season (latest team), plus the 40-man and
    injured list from the store when the fetch recorded them."""
    meta = ((ctx.store.get("meta") or {}).get("rosters") or {}).get(tid) or {}
    inj = {str(x[0]): x[1:] for x in (meta.get("injured") or []) if x}
    out = []
    for pid, r in hp.items():
        if r.get("team") == tid:
            out.append({"pid": pid, "name": r["name"], "pos": r.get("pos"), "kind": "hitter", "pa": r.get("pa"),
                        "war": r["values"].get("war"), "woba": r["values"].get("woba"), "xwoba_plus": r["values"].get("xwoba_plus"),
                        **{k: r["values"].get(k) for k in ROSTER_H}, "injured": inj.get(pid)})
    for pid, r in pp.items():
        if r.get("team") == tid:
            out.append({"pid": pid, "name": r["name"], "pos": r.get("role"), "kind": "pitcher", "ip": r["values"].get("ip"),
                        "war": r["values"].get("war"), "ra9": r["values"].get("ra9"), "stuff_plus": r["values"].get("stuff_plus"),
                        **{k: r["values"].get(k) for k in ROSTER_P}, "injured": inj.get(pid)})
    out.sort(key=lambda x: -(x.get("war") or -99))
    rn, rp = meta.get("names") or {}, meta.get("pos") or {}
    for pid in meta.get("40man") or []:
        if str(pid) not in {x["pid"] for x in out}:
            nm = ctx.name(pid)
            if not nm or nm == str(pid):
                nm = rn.get(str(pid)) or nm
            out.append({"pid": str(pid), "name": nm, "pos": (ctx.players.get(str(pid)) or {}).get("pos") or rp.get(str(pid)), "kind": "40man",
                        "injured": inj.get(str(pid))})
    return out
