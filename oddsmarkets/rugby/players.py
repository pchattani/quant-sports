"""
Players for The Quant Scrum: minutes from the substitutions, positions, per-80 rates shrunk toward the position,
percentiles within the position, and "Scrum value" (points added per 80 minutes above a replacement-level player).

Positions (ESPN's codes; replacements are listed as "R", so a replacement takes the position the player most often
starts in, else the athlete's listed position, else the bench jersey's usual role):
    front row  P (prop), H (hooker)        lock  L        back row  FL (flanker), N8 (number 8)
    halves     SH (scrum-half), FH (fly-half)              centres  C        back three  W (wing), FB (full-back)

Minutes: a starter plays from 0 to the minute they are replaced (80 if never); a replacement from the minute they come
on to 80 (or the minute they go off again). With no substitution events in the feed, starters get 80 and replacements
20 (flagged `est`). Cards are ignored (a sin-binned player is still on the team sheet).

Rates: per 80 minutes. A shown rate is shrunk toward the position's mean as if the player had also played
`PRIOR_MIN` minutes at that mean (the Rink and Hardwood shrink rates the same way), so a 30-minute cameo cannot top
a leaderboard.

Scrum value (ours): a ridge regression of the match margin on the two sides' differences in process stats (metres,
clean breaks, defenders beaten, offloads, tackles, missed tackles, turnovers conceded, penalties, cards, lineouts
won; volume stats that only track possession are left out: models.VALUE_TEAM), fitted on the development years only (models.fit_value). A player's value per
80 is the sum over those stats of weight x (the player's shrunk rate - the position's replacement rate, its 20th
percentile among qualified players), plus goal kicking above an average kicker. Scoring itself (tries) is not added
on top: the process stats that lead to tries already carry their value, and adding both would count it twice.
"""
from __future__ import annotations

import math
from collections import defaultdict

POS_GROUP = {"P": "front_row", "H": "front_row", "L": "lock", "FL": "back_row", "N8": "back_row",
             "SH": "halves", "FH": "halves", "C": "centres", "W": "back_three", "FB": "back_three"}
GROUP_NAME = {"front_row": "Front row", "lock": "Locks", "back_row": "Back row", "halves": "Half-backs",
              "centres": "Centres", "back_three": "Back three"}
GROUP_ORDER = ["front_row", "lock", "back_row", "halves", "centres", "back_three"]
POS_NAME = {"P": "Prop", "H": "Hooker", "L": "Lock", "FL": "Flanker", "N8": "Number 8", "SH": "Scrum-half",
            "FH": "Fly-half", "C": "Centre", "W": "Wing", "FB": "Full-back"}
ALIASES = {"PR": "P", "LH": "P", "TH": "P", "HK": "H", "LK": "L", "SR": "L", "BR": "FL", "F": "FL", "OF": "FL", "BF": "FL",
           "NE": "N8", "N": "N8", "8": "N8", "S": "SH", "HB": "SH", "F/H": "FH", "OH": "FH", "SO": "FH", "IC": "C",
           "OC": "C", "CE": "C", "WG": "W", "LW": "W", "RW": "W", "WI": "W", "FU": "FB", "B": "FB"}
JERSEY_POS = {1: "P", 2: "H", 3: "P", 4: "L", 5: "L", 6: "FL", 7: "FL", 8: "N8", 9: "SH", 10: "FH", 11: "W", 12: "C",
              13: "C", 14: "W", 15: "FB", 16: "H", 17: "P", 18: "P", 19: "L", 20: "FL", 21: "SH", 22: "FH", 23: "C"}
PRIOR_MIN = 240.0
QUAL_MIN = {"season": 160.0, "career": 400.0}       # minutes for a qualified percentile
RATE_KEYS = ["pts", "tries", "ta", "m", "car", "cb", "db", "off", "pas", "tk", "mt", "lo", "lot", "rk", "ml", "toc", "ko", "pc",
             "kfh", "yc", "rc", "con", "pg", "dg"]
LINEOUT_AVG, LINEOUT_PRIOR = 0.86, 30.0    # a hooker's throws: shrunk toward the average with 30 throws of weight
# process stats the value model weighs (player keys; the team keys in models.VALUE_TEAM)
# lineouts won is a team stat here: in the player feed it is the hooker's throws, so it is not a player's value
VALUE_KEYS = ["m", "cb", "db", "off", "tk", "mt", "toc", "pc", "yc", "rc"]


def norm_pos(code: str | None) -> str | None:
    c = str(code or "").upper().strip()
    if c in POS_GROUP:
        return c
    return ALIASES.get(c)


def minutes(match: dict, side: str) -> dict:
    """{athlete_id: (minutes, estimated)} for one side's matchday 23."""
    rows = match.get("l" + side) or []
    evs = [e for e in match.get("events") or [] if e[2] == side and e[1] in ("on", "off")]
    out = {}
    if not rows:
        return out
    if not evs:
        for r in rows:
            out[r[0]] = (80.0 if r[3] else 20.0, True)
        return out
    on_at, off_at = {}, {}
    for e in evs:
        mn = e[0] if e[0] is not None else 60
        mn = max(0, min(80, mn))
        if e[1] == "on":
            on_at.setdefault(e[3], mn)
        else:
            off_at.setdefault(e[3], mn)
    for r in rows:
        aid, starter = r[0], bool(r[3])
        if starter:
            m = off_at.get(aid, 80)
        elif aid in on_at:
            m = max(0, off_at.get(aid, 80) - on_at[aid]) if off_at.get(aid, 80) > on_at[aid] else 80 - on_at[aid]
        else:
            m = 0
        out[aid] = (float(max(0, min(80, m))), False)
    return out


def assign_positions(matches: list[dict], athletes: dict) -> dict:
    """athlete_id -> position code: the most common starting position, else the listed one, else the bench jersey."""
    starts = defaultdict(lambda: defaultdict(int))
    bench = defaultdict(lambda: defaultdict(int))
    for m in matches:
        for side in ("h", "a"):
            for r in m.get("l" + side) or []:
                p = norm_pos(r[2])
                if r[3] and p:
                    starts[r[0]][p] += 1
                elif not r[3] and isinstance(r[1], int):
                    jp = JERSEY_POS.get(r[1])
                    if jp:
                        bench[r[0]][jp] += 1
    out = {}
    ids = set(starts) | set(bench) | set(athletes)
    for aid in ids:
        if starts.get(aid):
            out[aid] = max(starts[aid].items(), key=lambda kv: kv[1])[0]
            continue
        p = norm_pos((athletes.get(aid) or {}).get("pos"))
        if p:
            out[aid] = p
        elif bench.get(aid):
            out[aid] = max(bench[aid].items(), key=lambda kv: kv[1])[0]
    return out


def player_games(matches: list[dict]) -> list[dict]:
    """Every player appearance with minutes: {mid, date, season, comp, team, opp, side, aid, jersey, starter,
    captain, min, est, stats, won, margin}."""
    out = []
    for m in matches:
        if m.get("status") != "final" or m.get("hs") is None:
            continue
        for side, opp in (("h", "a"), ("a", "h")):
            rows = m.get("l" + side) or []
            if not rows:
                continue
            mins = minutes(m, side)
            team = m["home" if side == "h" else "away"]
            other = m["home" if opp == "h" else "away"]
            pf = m["hs"] if side == "h" else m["as"]
            pa = m["as"] if side == "h" else m["hs"]
            for r in rows:
                mn, est = mins.get(r[0], (0.0, True))
                st = r[5] or {}
                if mn <= 0 and not any(st.get(k) for k in ("tk", "car", "pts", "pas")):
                    continue
                out.append({"mid": m["id"], "date": str(m.get("date") or "")[:10], "season": int(str(m.get("date"))[:4]),
                            "comp": m.get("comp"), "team": team["id"], "opp": other["id"], "side": side, "aid": r[0],
                            "jersey": r[1], "starter": bool(r[3]), "captain": bool(r[4]), "min": mn, "est": est,
                            "stats": st, "res": "W" if pf > pa else ("D" if pf == pa else "L"), "margin": pf - pa})
    return out


def aggregate(games: list[dict]) -> dict:
    """aid -> {"n", "starts", "min", "sums": {k: v}, "kick_att", "kick_made"}"""
    agg = {}
    for g in games:
        a = agg.setdefault(g["aid"], {"n": 0, "starts": 0, "min": 0.0, "sums": defaultdict(float), "kick_att": 0.0,
                                      "kick_made": 0.0, "teams": defaultdict(int), "first": g["date"], "last": g["date"],
                                      "w": 0, "d": 0, "l": 0, "capt": 0})
        a["n"] += 1
        a["starts"] += 1 if g["starter"] else 0
        a["capt"] += 1 if g["captain"] else 0
        a["min"] += g["min"]
        a["teams"][g["team"]] += 1
        a["first"] = min(a["first"], g["date"])
        a["last"] = max(a["last"], g["date"])
        a[{"W": "w", "D": "d", "L": "l"}[g["res"]]] += 1
        st = g["stats"]
        for k in RATE_KEYS:
            v = st.get(k)
            if isinstance(v, (int, float)):
                a["sums"][k] += v
        made = (st.get("con") or 0) + (st.get("pg") or 0)
        kp = st.get("kpct")
        if made and isinstance(kp, (int, float)) and kp > 0:
            a["kick_made"] += made
            a["kick_att"] += made / kp
    return agg


def rates(a: dict, prior: dict | None = None, prior_min: float = PRIOR_MIN) -> dict:
    """Per-80 rates, shrunk toward `prior` (the position's mean rates) with `prior_min` minutes of weight."""
    mins = max(a["min"], 1e-9)
    out = {}
    for k in RATE_KEYS:
        s = a["sums"].get(k, 0.0)
        if prior and k in prior:
            out[k] = 80.0 * (s + prior[k] * prior_min / 80.0) / (mins + prior_min)
        else:
            out[k] = 80.0 * s / mins
    car = a["sums"].get("car", 0.0)
    out["mpc"] = (a["sums"].get("m", 0.0) + 4.0 * 10) / (car + 10) if car or prior else None   # metres a carry, shrunk
    tk, mt = a["sums"].get("tk", 0.0), a["sums"].get("mt", 0.0)
    out["tkpct"] = (tk + 0.88 * 20) / (tk + mt + 20)                                         # tackle success, shrunk
    out["kpct"] = (a["kick_made"] + 0.72 * 8) / (a["kick_att"] + 8) if a["kick_att"] >= 1 else None
    # rugby-specific (2 Nov 2026): the hooker's lineout throws (the player feed's "lineouts won" is the thrower's),
    # shrunk; cards (a red counts as two yellows); goal-kicking points; involvements (carries + tackles + rucks)
    lot = a["sums"].get("lot", 0.0)
    out["lopct"] = (a["sums"].get("lo", 0.0) + LINEOUT_AVG * LINEOUT_PRIOR) / (lot + LINEOUT_PRIOR) if lot >= 5 else None
    out["cards"] = out.get("yc", 0.0) + 2.0 * out.get("rc", 0.0)
    out["gkp"] = 2.0 * out.get("con", 0.0) + 3.0 * out.get("pg", 0.0) + 3.0 * out.get("dg", 0.0)
    out["inv"] = out.get("car", 0.0) + out.get("tk", 0.0) + out.get("rk", 0.0)
    return out


def percentile_table(values: list[float]) -> list[float]:
    return sorted(v for v in values if v is not None and not math.isnan(v))


def pct_of(sorted_vals: list[float], v: float | None, lower_better: bool = False) -> float | None:
    if v is None or not sorted_vals:
        return None
    import bisect
    lo = bisect.bisect_left(sorted_vals, v)
    hi = bisect.bisect_right(sorted_vals, v)
    p = 100.0 * ((lo + hi) / 2.0) / len(sorted_vals)
    return round(100.0 - p if lower_better else p, 1)


def value_per80(r: dict, weights: dict, repl: dict, kick_avg: float = 0.72) -> float:
    """Scrum value per 80: sum over VALUE_KEYS of weight x (rate - replacement rate), plus goal kicking above average
    (points from conversions and penalties made beyond what an average kicker makes from the same attempts)."""
    v = 0.0
    for k in VALUE_KEYS:
        w = weights.get(k)
        if w is None or r.get(k) is None:
            continue
        v += w * (r[k] - repl.get(k, 0.0))
    return v
