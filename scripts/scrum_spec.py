#!/usr/bin/env python
"""
Write the rugby metric spec, docs/_design/metrics/rugby.json (the machine-readable METRICS_SPEC for The Quant Scrum),
with every number measured on our own data: year-to-year reliability, split-half reliability and the minutes a
metric needs to settle (m50), and how well each predicts next year's Scrum value. Groups: the six position groups
(front row, locks, back row, half-backs, centres, back three) and the teams.

    uv run python scripts/scrum_spec.py

Method (as the other sports' specs): player-years with 160+ minutes; yoy_r is the Pearson r of a player's per-80 rate
in year t and t+1 (both qualified, z-scored within year and group); split_half_r is the r between a player's odd and
even appearances in a year (Fisher-averaged over years), m50 = mean half-sample minutes x (1 - r) / r; the predictive
r is against next year's Scrum value per 80. Raw (unshrunk) rates are used for reliability.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.rugby import analytics as AN, build as B, models, players as PL, store  # noqa: E402

OUT = ROOT / "docs" / "_design" / "metrics" / "rugby.json"
EXPLAIN = {
    "val80": "Our player value: points added to the final margin per 80 minutes above a replacement-level player in the same position group, from what each carry, break, tackle, turnover and penalty is worth (a model fitted on 2004-2018 tests), plus goal kicking above an average kicker.",
    "pts": "Points scored per 80 minutes: tries, conversions, penalties and drop goals.",
    "tries": "Tries per 80 minutes.", "ta": "Try assists (the last pass or kick before a try) per 80 minutes.",
    "m": "Metres gained with the ball in hand per 80 minutes.", "car": "Carries (runs with the ball) per 80 minutes.",
    "mpc": "Metres per carry: how far a carry goes on average.", "cb": "Clean breaks (carries through the defensive line) per 80 minutes.",
    "db": "Defenders beaten per 80 minutes.", "off": "Offloads (passes out of a tackle) per 80 minutes.", "pas": "Passes per 80 minutes.",
    "tk": "Tackles made per 80 minutes.", "tkpct": "Tackle success: tackles made out of tackles attempted.",
    "mt": "Missed tackles per 80 minutes (fewer is better).", 
    "rk": "Rucks won per 80 minutes.", "toc": "Turnovers conceded per 80 minutes (fewer is better).",
    "pc": "Penalties conceded per 80 minutes (fewer is better).", "kfh": "Kicks from hand per 80 minutes.",
    "kpct": "Goal-kicking success: conversions and penalties kicked out of attempts.",
}
UNIT = {"mpc": "metres per carry", "tkpct": "%", "kpct": "%", "val80": "points per 80"}
HEAD = {
    "front_row": ["val80", "tk", "tkpct", "car", "m", "rk", "db", "pc"], "lock": ["val80", "tk", "tkpct", "car", "m", "rk", "db", "pc"],
    "back_row": ["val80", "tk", "car", "m", "db", "tkpct", "off", "pc"], "halves": ["val80", "pts", "pas", "kfh", "kpct", "ta", "m", "tk"],
    "centres": ["val80", "m", "cb", "db", "car", "off", "ta", "tk"], "back_three": ["val80", "m", "cb", "db", "tries", "mpc", "kfh", "tk"],
}
VIEW_WHY = {
    "front_row": "Props and hookers: the tackle count and its success, carries and rucks; the set piece itself is a team stat.",
    "lock": "Locks: the tackle and carry work (lineout wins are a team stat in our source).", "back_row": "Flankers and number 8s: tackles, carries and the metres after contact.",
    "halves": "Scrum-halves and fly-halves: points (the goal kicker), passing, kicking and try assists.",
    "centres": "Centres: metres, breaks and defenders beaten, then offloads and try assists.",
    "back_three": "Wings and full-backs: metres, breaks, tries and the kicking game.",
}


def pearson(a, b):
    n = len(a)
    if n < 8:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if not va or not vb:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb)


def raw_rate(a: dict, k: str):
    if k == "mpc":
        return a["sums"].get("m", 0) / a["sums"]["car"] if a["sums"].get("car") else None
    if k == "tkpct":
        t, m = a["sums"].get("tk", 0), a["sums"].get("mt", 0)
        return t / (t + m) if t + m else None
    if k == "kpct":
        return a["kick_made"] / a["kick_att"] if a["kick_att"] >= 3 else None
    return 80.0 * a["sums"].get(k, 0.0) / a["min"] if a["min"] else None


def main() -> int:
    matches, ath = store.load_all("men")
    fin = models.eligible(matches)
    fit = B.load_params("men")
    ana = AN.player_tables(fin, ath, date.today().isoformat(), fit.get("value"))
    ids = [m[0] for m in AN.PLAYER_METRICS]
    # player-year rows
    rows = defaultdict(dict)     # (grp, year) -> aid -> {metric: raw}
    halves = defaultdict(list)   # (grp, metric) -> [(odd, even, min_half)]
    for aid, rec in ana["players"].items():
        g = rec["grp"]
        if not g:
            continue
        gs_all = ana["games"][aid]
        for y, s in rec["seasons"].items():
            a = s["agg"]
            if a["min"] < PL.QUAL_MIN["season"]:
                continue
            vals = {k: raw_rate(a, k) for k in ids if k != "val80"}
            vals["val80"] = s["rates"].get("val80")
            rows[(g, y)][aid] = vals
            gs = [x for x in gs_all if x["season"] == y and x["stats"]]
            if len(gs) >= 4:
                odd = PL.aggregate(gs[0::2])[aid]
                even = PL.aggregate(gs[1::2])[aid]
                for k in ids:
                    if k == "val80":
                        continue
                    o, e = raw_rate(odd, k), raw_rate(even, k)
                    if o is not None and e is not None:
                        halves[(g, k)].append((o, e, (odd["min"] + even["min"]) / 2))
    groups = []
    for g in ["front_row", "lock", "back_row", "halves", "centres", "back_three"]:
        years = sorted(y for (gg, y) in rows if gg == g)
        mets = []
        for order, k in enumerate(HEAD[g] + [x for x in ids if x not in HEAD[g]], start=1):
            # year to year, z-scored within year
            a, b, nxt_a, nxt_v = [], [], [], []
            for y in years:
                cur, nx = rows.get((g, y), {}), rows.get((g, y + 1), {})
                def z(d):
                    vs = [v[k] for v in d.values() if v.get(k) is not None]
                    if len(vs) < 5:
                        return {}
                    m = sum(vs) / len(vs)
                    sd = math.sqrt(sum((x - m) ** 2 for x in vs) / len(vs)) or 1.0
                    return {aid: (v[k] - m) / sd for aid, v in d.items() if v.get(k) is not None}
                zc, zn = z(cur), z(nx)
                for aid in zc:
                    if aid in zn:
                        a.append(zc[aid])
                        b.append(zn[aid])
                    if aid in nx and nx[aid].get("val80") is not None and cur[aid].get(k) is not None:
                        nxt_a.append(cur[aid][k])
                        nxt_v.append(nx[aid]["val80"])
            yoy = pearson(a, b)
            hs = halves.get((g, k), [])
            sh = pearson([x[0] for x in hs], [x[1] for x in hs]) if hs else None
            nbar = sum(x[2] for x in hs) / len(hs) if hs else None
            m50 = round(nbar * (1 - sh) / sh) if (sh and sh > 0.05 and nbar) else None
            pred = pearson(nxt_a, nxt_v)
            label, short, d, fam = next((l, s, dd, f) for i, l, s, dd, f in AN.PLAYER_METRICS if i == k)
            mets.append({"id": k, "display": label, "short": short, "unit": UNIT.get(k, "per 80"), "unit_short": "%" if UNIT.get(k) == "%" else ("m/carry" if k == "mpc" else "/80"),
                         "direction": d, "set": "headline" if k in HEAD[g] else "secondary", "order": order, "basis": "rate", "family": fam,
                         "explanation": EXPLAIN[k], "in_payload": True,
                         "reliability": {"yoy_r": None if yoy is None else round(yoy, 3), "n_pairs": len(a), "split_half_r": None if sh is None else round(sh, 3),
                                         "split_half_r_sb": None if sh is None else round(2 * sh / (1 + sh), 3), "m50": m50, "m50_unit": "minutes"},
                         "predictive": {"target": "next-year Scrum value per 80", "r": None if pred is None else round(pred, 3)}})
        groups.append({"id": g, "entity": "player", "display": PL.GROUP_NAME[g], "peer_group": "position group " + g + " (" + ", ".join(p for p, gg in PL.POS_GROUP.items() if gg == g) + ")",
                       "position_field": "grp", "position_codes": [g], "minimum": {"field": "min", "value": PL.QUAL_MIN["season"], "unit": "minutes", "note": "minutes in the window (the last two years on the Board, a calendar year for a season row)"},
                       "basis": "per 80 minutes, shrunk toward the group with 240 minutes of prior", "metrics": mets,
                       "view": {"why": VIEW_WHY[g], "excel": HEAD[g][1:4], "value": ["val80"], "x": HEAD[g][1], "y": HEAD[g][2], "color": "val80"}})
    tm = []
    for order, (i, l, d, grp, _h) in enumerate(AN.TEAM_METRICS, start=1):
        tm.append({"id": i, "display": l, "short": AN.TEAM_SHORT[i], "unit": AN.TEAM_UNITS.get(i, "per test"), "direction": d, "set": "headline" if order <= 12 else "secondary",
                   "order": order, "style": i in AN.STYLE, "explanation": l + (" (a share)" if AN.TEAM_UNITS.get(i) == "%" else " per test") + ", opponent-adjusted over the last two years.", "in_payload": True, "group": grp})
    groups.append({"id": "teams", "entity": "team", "display": "Teams", "peer_group": "test sides with six or more tests in two years", "metrics": tm})
    spec = {"sport": "rugby", "site": "scrum", "schema_version": 1, "generated": date.today().isoformat(), "leagues": ["men", "women"],
            "payloads": {"players": "docs/scrum/data/<S>/players.json -> cols/rows (id, n, team, pos, grp, age, gp, min, q, <metric>, p_<metric>)",
                         "player_pages": "docs/scrum/data/<S>/players/<id>.json -> cur.v / cur.pc, seasons[].v / .pc",
                         "teams": "docs/scrum/data/<S>/teams.json -> teams[].m{id: [value, percentile]}"},
            "method": {"seasons": "calendar years 2006 to now (player statistics); 160+ minutes a year to qualify", "yoy": "Pearson r of per-80 rates in consecutive years, z-scored within year and group",
                       "split_half": "odd v even appearances within a year", "m50": "mean half-sample minutes x (1 - r) / r", "predictive": "r with next year's Scrum value per 80"},
            "groups": groups,
            "our_models": {"models": {"value": {"name": "Scrum value", "about": "Our player value: points added per 80 minutes above a replacement-level player in the same position, from a regression of the final margin on the process statistics."},
                                      "rating": {"name": "Our team rating", "about": "Points better than an average test side on a neutral ground, with home advantage, travel and rest taken out."}},
                           "metrics": {"val80": "value", "rating": "rating"}}}
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for g in groups[:-1]:
        print(g["id"], [(m["id"], m["reliability"]["yoy_r"], m["reliability"]["m50"]) for m in g["metrics"][:8]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
