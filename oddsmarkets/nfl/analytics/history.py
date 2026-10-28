"""
history.json: 1999 onward. Single-season leaderboards on era-adjusted rates (100 + 10 z within the season's qualified
pool), career totals since 1999, and league trends by season (points, EPA per play, pass rate, success, fourth-down go
rate, penalties, field-goal accuracy). Built from each season's reduced catalogue (careers.reduce_cat) and a small
league summary per season (`league_summary`, cached in the season manifest).
"""
from __future__ import annotations

from oddsmarkets.nfl import analytics as an
from oddsmarkets.nfl.analytics.context import SeasonContext, flag, num

SEASON_BOARDS = [("QB", "epa_db", "EPA / dropback"), ("QB", "anya", "ANY/A"), ("QB", "cpoe", "CPOE"), ("QB", "composite", "QB composite"),
                 ("RB", "rush_epa", "EPA / carry"), ("RB", "ypc", "Yards / carry"), ("WR", "rec_epa_tgt", "EPA / target (WR)"),
                 ("WR", "target_share", "Target share (WR)"), ("TE", "rec_epa_tgt", "EPA / target (TE)"), ("K", "fg_oe", "FG over expected"),
                 ("P", "net", "Net punt average"), ("DEF", "def_value", "Splash EPA")]
# single-season boards need a full season's volume (a hot September does not make an all-time list)
SEASON_FLOOR = {"QB": ("att", 250), "RB": ("carries", 120), "WR": ("targets", 60), "TE": ("targets", 45), "K": ("fga", 18),
                "P": ("punts", 40), "DEF": ("tackles", 40)}
# single-season records in our data (1999 on), for "records in reach": [key, group (None = any), label]
RECORD_KEYS = [("pass_yds", "QB", "Passing yards"), ("pass_td", "QB", "Passing touchdowns"), ("rush_yds", None, "Rushing yards"),
               ("rush_td", None, "Rushing touchdowns"), ("rec_yds", None, "Receiving yards"), ("rec_td", None, "Receiving touchdowns"),
               ("sacks", "DEF", "Sacks"), ("ints", "DEF", "Interceptions")]
CAREER_BOARDS = [("QB", "pass_yds", "Passing yards"), ("QB", "pass_td", "Passing TD"), ("QB", "epa_total", "Total EPA (QB)"),
                 (None, "value", "Gridiron Value"), ("RB", "rush_yds", "Rushing yards"), ("RB", "rush_td", "Rushing TD"),
                 (None, "rec_yds", "Receiving yards"), (None, "rec_td", "Receiving TD"), ("DEF", "sacks", "Sacks"),
                 ("DEF", "ints", "Interceptions"), ("K", "fgm", "Field goals made"), ("K", "fg_oe", "FG over expected")]


def league_summary(ctx: SeasonContext) -> dict | None:
    P = ctx.pbp()
    if not len(P) or "season_type" not in P:
        return None
    R = P[P["season_type"].astype(str).str.upper() == "REG"]
    S = R[R["play_type"].isin(["pass", "run"])] if "play_type" in R else R.iloc[0:0]
    if not len(S):
        return None
    games = [g for g in ctx.games.values() if g.get("gtype") == "REG" and g.get("status") == "final" and g.get("hs") is not None]
    pts = [int(g["hs"]) + int(g["as"]) for g in games]
    home_w = [1.0 if g["hs"] > g["as"] else (0.5 if g["hs"] == g["as"] else 0.0) for g in games]
    F = R[R["play_type"] == "field_goal"] if "play_type" in R else R.iloc[0:0]
    D4 = R[(num(R, "down") == 4) & R["play_type"].isin(["pass", "run", "punt", "field_goal"])] if "play_type" in R else R.iloc[0:0]
    D4 = D4[(num(D4, "half_seconds_remaining") > 120) & num(D4, "wp").between(0.05, 0.95)]
    epa = num(S, "epa")
    db = flag(S, "qb_dropback").fillna(0) == 1
    return {"season": ctx.season, "games": len(games), "ppg": an.rnd(sum(pts) / (2 * len(pts)), 2) if pts else None,
            "home_win": an.rnd(sum(home_w) / len(home_w), 3) if home_w else None, "epa_play": an.rnd(epa.mean(), 4),
            "pass_epa": an.rnd(epa[db].mean(), 4), "rush_epa": an.rnd(epa[~db].mean(), 4), "pass_rate": an.rnd(db.mean(), 3),
            "success": an.rnd((epa > 0).mean(), 3), "go_rate": an.rnd(D4["play_type"].isin(["pass", "run"]).mean(), 3) if len(D4) else None,
            "fg_pct": an.rnd((F["field_goal_result"].astype(str) == "made").mean(), 3) if len(F) else None,
            "sack_rate": an.rnd(flag(S[db], "sack").mean(), 3), "int_rate": an.rnd(flag(S[db], "interception").mean(), 4),
            "penalties_pg": an.rnd(flag(R, "penalty").fillna(0).sum() / max(1, R["game_id"].nunique()), 2),
            "cpoe_available": bool(num(S, "cpoe").notna().any()), "adot": an.rnd(num(S[db], "air_yards").mean(), 2)}


ROUND = {"WC": 1, "DIV": 2, "CON": 3, "SB": 4}
RESULT = {0: "Missed the playoffs", 1: "Lost in the Wild Card round", 2: "Lost in the Divisional round", 3: "Lost the conference final",
          4: "Lost the Super Bowl", 5: "Won the Super Bowl"}


def champions(stores: dict[int, dict]) -> dict | None:
    """Every season since 1999 from the season stores: the Super Bowl (winner, loser, score), the two conference
    champions, the best regular-season record, and each franchise's season (record, points, how far it went: 0 missed
    the playoffs ... 5 won the Super Bowl). Franchises carry their current abbreviation (OAK -> LV, SD -> LAC, STL -> LA,
    store `franchise`), with the season's own abbreviation kept as `as`."""
    seasons, teams = [], {}
    for s in sorted(stores):
        st = stores.get(s) or {}
        G = [g for g in (st.get("games") or {}).values() if g.get("status") == "final" and g.get("hs") is not None and g.get("as") is not None]
        T = st.get("teams") or {}
        fr = {k: (v.get("franchise") or k) for k, v in T.items()}
        conf = {k: v.get("conf") for k, v in T.items()}
        post = [g for g in G if g.get("gtype") in ROUND]
        sb = [g for g in post if g.get("gtype") == "SB"]
        reg = [g for g in G if g.get("gtype") == "REG"]
        if not reg:
            continue

        def win(g):
            return (g["home"], g["away"], g["hs"], g["as"]) if g["hs"] > g["as"] else (g["away"], g["home"], g["as"], g["hs"])
        row: dict = {"season": int(s)}
        if sb:
            w, l, ws, ls = win(sb[0])
            row["sb"] = [fr.get(w, w), fr.get(l, l), ws, ls]
        for g in post:
            if g.get("gtype") == "CON":
                w = win(g)[0]
                if conf.get(w):
                    row[str(conf[w]).lower()] = fr.get(w, w)
        rec: dict[str, list] = {}
        for g in reg:
            for t, me, op in ((g["home"], g["hs"], g["as"]), (g["away"], g["as"], g["hs"])):
                r = rec.setdefault(t, [0, 0, 0, 0, 0])
                r[0 if me > op else 1 if me < op else 2] += 1
                r[3] += me
                r[4] += op
        far = {t: 0 for t in rec}
        for g in post:
            k = ROUND[g["gtype"]]
            w, l = win(g)[0], win(g)[1]
            far[l] = max(far.get(l, 0), k)
            far[w] = max(far.get(w, 0), k + 1 if g["gtype"] == "SB" else k)
        best = max(rec, key=lambda t: ((rec[t][0] + 0.5 * rec[t][2]) / max(1, sum(rec[t][:3])), rec[t][3] - rec[t][4]))
        row["best"] = [fr.get(best, best)] + rec[best][:3]
        try:                                                    # the AP award winners (models/award_winners.py, 2006 on)
            from oddsmarkets.nfl.models.award_winners import WINNERS
            aw = {k: list(v[int(s)]) for k, v in WINNERS.items() if int(s) in v}
            if aw:
                row["awards"] = aw
        except ImportError:
            pass
        seasons.append(row)
        for t, r in rec.items():
            teams.setdefault(fr.get(t, t), []).append([int(s), r[0], r[1], r[2], r[3], r[4], far.get(t, 0)] + ([t] if fr.get(t, t) != t else []))
    if not seasons:
        return None
    return {"cols": ["season", "w", "l", "t", "pf", "pa", "far", "as"], "far": RESULT, "seasons": seasons, "teams": teams}


def build(rows_by_season: dict[int, dict | None], league: dict[int, dict | None], stores: dict[int, dict] | None = None) -> dict | None:
    if not rows_by_season:
        return None
    season_boards = {}
    for grp, k, label in SEASON_BOARDS:
        cand = []
        for s, rows in rows_by_season.items():
            for pid, r in (rows or {}).items():
                fk, fv = SEASON_FLOOR.get(grp, ("games", 0))
                if r.get("group") == grp and r.get("qualified") and (r.get("plus") or {}).get(k) is not None                         and (an.fnum((r.get("values") or {}).get(fk)) or 0) >= fv:
                    cand.append([pid, r.get("name"), s, r.get("team"), (r.get("values") or {}).get(k), r["plus"][k]])
        cand.sort(key=lambda x: -x[5])
        season_boards[f"{grp.lower()}_{k}"] = {"label": label, "group": grp, "key": k, "rows": cand[:25]}
    career_boards = {}
    for grp, k, label in CAREER_BOARDS:
        tot: dict[str, dict] = {}
        for s, rows in rows_by_season.items():
            for pid, r in (rows or {}).items():
                if grp is not None and r.get("group") != grp:
                    continue
                v = an.fnum((r.get("values") or {}).get(k))
                if v is None:
                    continue
                e = tot.setdefault(pid, {"name": r.get("name"), "v": 0.0, "first": s, "last": s, "seasons": 0, "team": r.get("team")})
                e["v"] += v
                e["first"], e["last"] = min(e["first"], s), max(e["last"], s)
                e["seasons"] += 1
                if s >= e["last"]:
                    e["team"] = r.get("team")
        rows = sorted(([p, e["name"], e["first"], e["last"], e["seasons"], round(e["v"], 2)] for p, e in tot.items()), key=lambda x: -x[5])
        career_boards[f"{(grp or 'all').lower()}_{k}"] = {"label": label, "group": grp, "key": k, "rows": rows[:25]}
    # the single-season records in our data: the ten best seasons per key (a page takes the best before the season it shows)
    records = {}
    for k, grp, label in RECORD_KEYS:
        cand = []
        for s, rows in rows_by_season.items():
            for pid, r in (rows or {}).items():
                if grp is not None and r.get("group") != grp:
                    continue
                v = an.fnum((r.get("pv") or {}).get(k, (r.get("values") or {}).get(k)))
                if v is not None and v > 0:
                    cand.append([pid, r.get("name"), s, r.get("team"), round(v, 1)])
        cand.sort(key=lambda x: (-x[4], x[2]))
        records[k] = {"label": label, "group": grp, "rows": cand[:10]}
    trends = [league[s] for s in sorted(league) if league.get(s)]
    return {"ok": True, "updated_at": an.now(), "seasons": sorted(rows_by_season), "season_cols": ["pid", "name", "season", "team", "value", "plus"],
            "season_records": records, "record_cols": ["pid", "name", "season", "team", "value"],
            "champions": champions(stores) if stores else None,
            "season_leaders": season_boards, "career_cols": ["pid", "name", "first", "last", "seasons", "total"], "career_leaders": career_boards,
            "league": trends, "era_note": "plus = 100 + 10 z within the season's qualified pool at the position (lower-is-better rates reversed).",
            "season_floor": {g: {"metric": k, "min": v} for g, (k, v) in SEASON_FLOOR.items()},
            "coverage": {"pbp": "1999 onward", "cpoe": "2009 onward (our completion model; air yards on incompletions start in 2009)", "ngs": "2016 onward", "participation": "2016-2025",
                         "ftn": "2022 onward"}}
