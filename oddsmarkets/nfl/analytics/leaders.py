"""
leaders.json, lab.json, awards.json and glossary.json.

Leaders: the top 10 qualified players per catalogue metric and position group, and the 32 teams ranked per team metric.
Lab: the whole catalogue column-oriented per position group, for the scatter / table lab and compare pages.
Awards: the award model (MVP, OPOY, DPOY, OROY, DROY, CPOY, COTY) with market prices; when it is not available,
candidates ranked by our value metrics (no probabilities).
Glossary: every metric with its stabilisation sample, the model entries, the percentile / qualification rules and the
data notices.
"""
from __future__ import annotations

from oddsmarkets.nfl import analytics as an
from oddsmarkets.nfl.analytics import players as PL
from oddsmarkets.nfl.analytics import teams as TM

HEADLINE = {"QB": ["composite", "epa_db", "cpoe", "anya", "value", "success", "pass_yds", "pass_td"],
            "RB": ["value", "rush_epa", "ryoe", "rush_success", "explosive", "rush_yds", "rush_td"],
            "WR": ["value", "rec_epa", "rec_epa_tgt", "target_share", "wopr", "yacoe", "croe", "rec_yds"],
            "TE": ["value", "rec_epa", "rec_epa_tgt", "target_share", "yacoe", "rec_yds"],
            "K": ["fg_oe", "pts_oe", "fg_pct", "fg_50"], "P": ["epa_punt", "net", "inside20"],
            "DEF": ["def_value", "sacks", "splash_pg", "ints", "pd", "tfl"]}
INDEX_LEADERS = [("QB", "composite"), ("QB", "epa_db"), ("QB", "cpoe"), ("RB", "rush_epa"), ("RB", "ryoe"), ("WR", "rec_epa"),
                 ("TE", "rec_epa"), ("DEF", "sacks"), ("K", "fg_oe")]


def build(season: int, cat: dict | None, tms: dict | None) -> dict | None:
    if not cat or not cat.get("ok"):
        return None
    players = cat.get("players") or {}
    out: dict[str, dict] = {}
    mets = {m["key"]: m for m in cat.get("metrics") or []}
    for grp, keys in (cat.get("groups") or {}).items():
        boards = {}
        for k in keys:
            m = mets.get(k)
            if not m:
                continue
            cand = [(p, r) for p, r in players.items() if r.get("group") == grp and r.get("qualified") and (r.get("values") or {}).get(k) is not None]
            cand.sort(key=lambda x: x[1]["values"][k], reverse=not m.get("lower"))
            boards[k] = [[p, r.get("name"), r.get("team"), r["values"][k]] for p, r in cand[:10]]
        out[grp] = boards
    team_b = {}
    tt = (tms or {}).get("teams") or {}
    for m in TM.METRICS:
        vals = [(t, (r.get("values") or {}).get(m["key"])) for t, r in tt.items()]
        vals = [x for x in vals if x[1] is not None]
        vals.sort(key=lambda x: x[1], reverse=not m.get("lower"))
        team_b[m["key"]] = [[t, v] for t, v in vals]
    return {"ok": True, "season": season, "updated_at": an.now(), "cols": ["pid", "name", "team", "value"], "players": out, "teams": team_b,
            "headline": HEADLINE, "metrics": cat.get("metrics")}


def index_leaders(cat: dict | None) -> dict:
    """{"<group>_<key>": [[pid, value], ...] x10} for the hub."""
    out = {}
    if not cat or not cat.get("players"):
        return out
    mets = {m["key"]: m for m in cat.get("metrics") or []}
    for grp, k in INDEX_LEADERS:
        m = mets.get(k)
        if not m:
            continue
        cand = [(p, (r.get("values") or {}).get(k)) for p, r in cat["players"].items() if r.get("group") == grp and r.get("qualified")
                and (r.get("values") or {}).get(k) is not None]
        cand.sort(key=lambda x: x[1], reverse=not m.get("lower"))
        out[f"{grp.lower()}_{k}"] = [[p, v] for p, v in cand[:10]]
    return out


def lab(season: int, cat: dict | None, tms: dict | None) -> dict | None:
    if not cat or not cat.get("ok"):
        return None
    groups = {}
    for grp, keys in (cat.get("groups") or {}).items():
        cols = ["pid", "name", "team", "pos", "age", "games", "qualified"] + keys + [f"pct_{k}" for k in keys]
        rows = []
        for p, r in (cat.get("players") or {}).items():
            if r.get("group") != grp:
                continue
            v, pc = r.get("values") or {}, r.get("pct") or {}
            rows.append([p, r.get("name"), r.get("team"), r.get("pos"), r.get("age"), r.get("games"), r.get("qualified")] +
                        [v.get(k) for k in keys] + [pc.get(k) for k in keys])
        groups[grp] = {"cols": cols, "rows": rows}
    tcols = ["team", "name", "colour"] + [m["key"] for m in TM.METRICS]
    trows = [[t, r.get("name"), r.get("colour")] + [(r.get("values") or {}).get(m["key"]) for m in TM.METRICS]
             for t, r in ((tms or {}).get("teams") or {}).items()]
    return {"ok": True, "season": season, "updated_at": an.now(), "groups": groups, "teams": {"cols": tcols, "rows": trows},
            "metrics": cat.get("metrics"), "team_metrics": (tms or {}).get("metrics")}


AWARD_NAMES = {"mvp": "Most Valuable Player", "opoy": "Offensive Player of the Year", "dpoy": "Defensive Player of the Year",
               "oroy": "Offensive Rookie of the Year", "droy": "Defensive Rookie of the Year", "cpoy": "Comeback Player of the Year",
               "coty": "Coach of the Year"}


def awards(ctx, cat: dict | None, model: dict | None) -> dict | None:
    """awards.json: our award races (with market prices and edges when fetched) when available, else candidates
    ranked by our value metrics (no probabilities); the verified winner of each award for completed seasons."""
    from oddsmarkets.nfl.analytics import adapters, people
    winners = adapters.award_winners(ctx.season)
    if isinstance(model, dict) and any(model.get("races") or {}):
        out = {}
        for k, rows in (model.get("races") or {}).items():
            mk = {str(r.get("name")): r for r in ((model.get("markets") or {}).get(k) or [])}
            cands = []
            for r in rows:
                m = mk.get(str(r.get("name"))) or {}
                pm, pk = an.fnum(r.get("p")), an.fnum(m.get("market"))
                cands.append({"pid": r.get("id"), "name": r.get("name"), "team": r.get("team"), "pos": r.get("pos"),
                              "p_model": an.rnd(pm, 4), "p_market": an.rnd(pk, 4),
                              "edge": an.rnd(pm - pk, 4) if pm is not None and pk is not None else None})
            out[k] = {"name": AWARD_NAMES.get(k, k), "candidates": cands, "winner": winners.get(k)}
        for k, w in winners.items():
            out.setdefault(k, {"name": AWARD_NAMES.get(k, k), "candidates": [], "winner": w})
        return {"ok": True, "season": ctx.season, "updated_at": an.now(), "source": "model", "awards": out,
                "share_played": model.get("share_played"), "markets_matched": bool(model.get("markets"))}
    if not cat or not cat.get("players"):
        return None
    P = cat["players"]

    def top(filter_fn, key, n=10):
        c = [(p, r) for p, r in P.items() if filter_fn(p, r) and (r.get("values") or {}).get(key) is not None]
        c.sort(key=lambda x: -x[1]["values"][key])
        return [{"pid": p, "name": r.get("name"), "team": r.get("team"), "pos": r.get("pos"), "score": r["values"][key], "metric": key,
                 "p_model": None, "p_market": None, "edge": None} for p, r in c[:n]]
    ppl = people.people()

    def rookie(p):
        return (ppl.get(p) or {}).get("rookie") == ctx.season or ((ppl.get(p) or {}).get("draft") or {}).get("year") == ctx.season
    out = {"mvp": top(lambda p, r: r.get("group") == "QB" and r.get("qualified"), "composite"),
           "opoy": top(lambda p, r: r.get("group") in ("RB", "WR", "TE"), "value"),
           "dpoy": top(lambda p, r: r.get("group") == "DEF", "def_value"),
           "oroy": top(lambda p, r: r.get("group") in ("QB", "RB", "WR", "TE") and rookie(p), "value"),
           "droy": top(lambda p, r: r.get("group") == "DEF" and rookie(p), "def_value")}
    aw = {k: {"name": AWARD_NAMES[k], "candidates": v, "winner": winners.get(k)} for k, v in out.items()}
    for k, w in winners.items():
        aw.setdefault(k, {"name": AWARD_NAMES.get(k, k), "candidates": [], "winner": w})
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "source": "ranking",
            "note": "Candidates ranked by our value metrics, without probabilities (the award model runs for the current "
                    "season only).", "awards": aw}


MODEL = [
    ("ep", "Expected points", "Play models", "Multinomial LightGBM next-score model (TD, FG, safety, none and the opponent's) on down, "
     "distance, field position, time, score, timeouts, home, roof and era; cross-fitted by season. EPA = EP after - EP before. "
     "Compared with nflfastR's EP on the Calibration page."),
    ("wp", "Win probability", "Play models", "Our own win-probability model on score, time, field position, down and distance, "
     "timeouts and the pre-game spread; compared with nflfastR's and ESPN's on every game page."),
    ("fourth_down", "Fourth-down decisions", "Play models", "Win probability of going for it, punting and kicking: conversion "
     "probability, punt net distance and field-goal make probability feed the WP model; the decision's grade is the WP lost "
     "against the best option."),
    ("completion", "Completion probability (CPOE)", "Play models", "P(completion) from air yards, target depth and location, "
     "pressure and (FTN) charting; CPOE = completions minus expected."),
    ("yac", "Expected YAC", "Play models", "Expected yards after the catch at the catch point; YACOE = actual - expected."),
    ("ryoe", "Rush yards over expected", "Play models", "Expected rushing yards from box count, down, distance, field position and "
     "formation (FTN / participation where available); NGS RYOE shown 2016 onward."),
    ("player_value", "Gridiron Value", "Value", "EPA attributed to passers, rushers and receivers (receivers credited with the "
     "air and YAC split), adjusted for opponent and supporting cast by ridge (RAPM-style) where participation exists."),
    ("qb", "QB composite", "Value", "EPA per dropback, CPOE, sack avoidance and turnover-worthy plays, each shrunk at its "
     "stabilisation rate, combined to 100 = average, 10 = one SD."),
    ("kicking", "Kicking", "Value", "Field-goal make probability by distance, weather, altitude and roof; FG over expected."),
    ("team_strength", "Team strength", "Prediction", "Opponent-adjusted unit ratings (pass and rush offence and defence, special "
     "teams) with time decay and priors, a separate QB component, in points per game against an average team."),
    ("game", "Game model", "Prediction", "Expected margin and total from team strength, home field (by season), rest, travel, time "
     "zones, weather and QB status; win, spread and total distributions with drive-level simulation."),
    ("season_sim", "Season simulation", "Prediction", "The remaining schedule simulated with the game model, the NFL tiebreakers "
     "and the seven-team conference playoffs with reseeding; division, playoff, bye and Super Bowl chances, magic numbers and draft order."),
    ("awards", "Award races", "Prediction", "MVP, OPOY, DPOY, OROY, DROY, CPOY and COTY from model value and voting features, fitted "
     "on a verified table of past winners."),
    ("epa_units", "EPA units", "Catalogue", "Opponent-adjusted EPA per play by unit: a ridge regression of play EPA on offence and "
     "defence indicators (penalty 60 plays per team)."),
    ("goe", "Go rate over expected", "Catalogue", "A coach's fourth-down go rate minus a league logistic model's expected go rate "
     "in the same situations (distance, field position, score, time, win probability), fitted per season."),
    ("percentile", "Percentiles", "Catalogue", "100 = best, reversed where lower is better; placed against the position group's "
     "reference pool after shrinking the value toward the pool mean with the metric's stabilisation constant ((n v + k m) / "
     "(n + k)); a metric needs its sample floor (50 dropbacks, 30 carries, 15 targets, 5 FG attempts, 10 punts) to get one. "
     "pct_pos compares within the listed position (defence: DL, LB, DB)."),
    ("stabilisation", "Stabilisation", "Catalogue", "The sample at which split-half reliability reaches 0.7: r(n) = n / (n + k), "
     "n_0.7 = 0.7 k / 0.3, k fitted per metric over seasons (our stabilise.py; published values where not fitted)."),
    ("era", "Era adjustment", "History", "History leaderboards rank season rates as z-scores within their own season's qualified "
     "pool (shown as 100 + 10 z), so 2007 and 2024 passing are compared against their own league."),
    ("gvar", "Value above replacement", "Value", "Points (EPA) above a replacement-level player at the same position: Gridiron "
     "Value's per-play rate in each role less the position's 20th-percentile rate, times plays (QB, RB, WR, TE); kickers' points over "
     "expected, punters' punting EPA and defenders' Splash EPA the same way. Offensive linemen are not valued individually."),
    ("starters_value", "Position value (team)", "Value", "The sum of a team's starters' per-game value above replacement at a "
     "position (QB 1, RB 2, WR 3, TE 2, outside pass rushers (ED) 2, interior line (DL) 2, LB 2, CB 3, S 2, K 1, P 1) from the current roster; the QB is the team-strength "
     "model's QB term. Graded A-F by percentile among the 32 teams on the team pages."),
    ("trade_curve", "Trade sensitivity curve", "Season simulation", "A team's playoff, division, bye, conference and Super Bowl chances, "
     "wins and draft slot as its strength is shifted (-10 to +10 points a game), from the season simulation re-weighted by importance "
     "sampling and anchored to the published chances; the trade simulator reads trades off it."),
]


def glossary() -> dict:
    groups: dict[str, list] = {}
    for m in PL.all_metrics():
        e = an.public_metric(m)
        e["kind"] = "player"
        groups.setdefault(f"Players: {m['group']}", []).append(e)
    for m in TM.METRICS:
        e = an.public_metric(m)
        e["kind"] = "team"
        groups.setdefault(f"Teams: {m['group']}", []).append(e)
    return {"ok": True, "updated_at": an.now(), "groups": [{"name": k, "entries": v} for k, v in groups.items()],
            "model": [{"key": k, "label": l, "group": g, "desc": d} for k, l, g, d in MODEL],
            "notices": {"nflverse": an.NFLVERSE_CREDIT, "ftn": an.FTN_CREDIT, "ngs": an.NGS_CREDIT}}
