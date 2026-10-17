"""
leaders.json and lab.json (per level and season).

leaders: the top N of every catalogue metric (hitters, pitchers, teams), direction-aware, among players over the
metric's sample floor and the reference pool's minimum (hitters PA, pitchers BF, scaled to the season's team games;
counting stats use everyone), plus the best pitches of each type by Stuff+ and Pitching+ (100+ thrown).

lab: column-oriented rows for any-two-metric scatter plots: {"fields": [...], "metrics": {kind: [METRIC]},
"rows": {kind: [[pid, name, team, pos, sample, v1, v2, ...]]}, "kinds": ["hitter", "pitcher"], "presets"}.
"""
from __future__ import annotations

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import hitters as H
from oddsmarkets.baseball.analytics import pitchers as P

TOP = 25
PRESETS = [
    {"kind": "pitcher", "x": "stuff_plus", "y": "ra9", "label": "Stuff against results"},
    {"kind": "pitcher", "x": "pitching_plus", "y": "xwoba_plus", "label": "Pitching+ against xwOBA+ allowed"},
    {"kind": "pitcher", "x": "fb_vaa", "y": "fb_whiff_pct", "label": "Fastball VAA against fastball whiff rate"},
    {"kind": "pitcher", "x": "tunnel_index", "y": "whiff_pct", "label": "Tunneling against whiff rate"},
    {"kind": "hitter", "x": "bat_speed", "y": "xwoba_plus", "label": "Bat speed against xwOBA+"},
    {"kind": "hitter", "x": "chase_pct", "y": "dv", "label": "Decision value against chase rate"},
    {"kind": "hitter", "x": "xwoba_savant", "y": "xwoba_plus", "label": "Savant xwOBA against xwOBA+"},
    {"kind": "hitter", "x": "pull_air_pct", "y": "iso", "label": "Pull-air rate against power"},
]


def _top(players: dict, metrics: list[dict], eligible) -> dict:
    out = {}
    for m in metrics:
        k = m["key"]
        cand = [(pid, r["values"].get(k)) for pid, r in players.items() if r["values"].get(k) is not None and eligible(r, m)]
        cand.sort(key=lambda x: x[1], reverse=not m.get("lower"))
        out[k] = [[pid, v, players[pid].get("name"), players[pid].get("team")] for pid, v in cand[:TOP]]
    return out


def build(ctx, hitters: dict | None, pitchers: dict | None, teams: dict | None) -> dict:
    out = {"ok": True, "level": ctx.level, "season": ctx.season, "updated_at": an.now(), "top": TOP}
    if hitters and hitters.get("ok", True) and hitters.get("players"):
        min_pa = (hitters.get("reference") or {}).get("min_pa") or 50

        def el_h(r, m):
            if m["fmt"] == "int" or not m.get("unit"):
                return r["pa"] >= 1
            return r["pa"] >= min_pa and ((r.get("n") or {}).get(m["unit"]) or 0) >= H.FLOORS.get(m["unit"], 0)
        out["hitters"] = _top(hitters["players"], hitters["metrics"], el_h)
        out["hitters_min_pa"] = min_pa
    if pitchers and pitchers.get("ok", True) and pitchers.get("players"):
        min_bf = (pitchers.get("reference") or {}).get("min_bf") or 50

        def el_p(r, m):
            if m["fmt"] == "int" or not m.get("unit"):
                return r["bf"] >= 1
            return r["bf"] >= min_bf and ((r.get("n") or {}).get(m["unit"]) or 0) >= P.FLOORS.get(m["unit"], 0)
        out["pitchers"] = _top(pitchers["players"], pitchers["metrics"], el_p)
        out["pitchers_min_bf"] = min_bf
        best: dict[str, dict] = {}
        for pid, a in (pitchers.get("arsenal") or {}).items():
            for pt, r in a.items():
                if (r.get("n") or 0) < 100:
                    continue
                for k in ("stuff", "pitching", "whiff"):
                    if r.get(k) is not None:
                        best.setdefault(pt, {}).setdefault(k, []).append([pid, r[k], pitchers["players"].get(pid, {}).get("name"),
                                                                        pitchers["players"].get(pid, {}).get("team"), r.get("n"), r.get("velo")])
        for pt in best:
            for k in best[pt]:
                best[pt][k] = sorted(best[pt][k], key=lambda x: -x[1])[:15]
        out["pitch_types"] = best
    if teams and teams.get("teams"):
        out["teams"] = {}
        for m in teams["metrics"]:
            vals = [(t, r["values"].get(m["key"])) for t, r in teams["teams"].items() if r["values"].get(m["key"]) is not None]
            vals.sort(key=lambda x: x[1], reverse=not m.get("lower"))
            out["teams"][m["key"]] = [[t, v] for t, v in vals]
    return out


def lab(ctx, hitters: dict | None, pitchers: dict | None) -> dict:
    out = {"ok": True, "level": ctx.level, "season": ctx.season, "updated_at": an.now(), "kinds": [],
           "fields": ["pid", "name", "team", "pos", "n"], "metrics": {}, "rows": {}, "presets": PRESETS}
    for kind, cat, nkey, floor in (("hitter", hitters, "pa", 50), ("pitcher", pitchers, "bf", 50)):
        if not cat or not cat.get("players"):
            continue
        mets = [m for m in cat["metrics"] if m["fmt"] != "int" or m["key"] in ("hr", "so", "w", "sv", "sb")]
        out["kinds"].append(kind)
        out["metrics"][kind] = mets
        rows = []
        for pid, r in cat["players"].items():
            if (r.get(nkey) or 0) < floor:
                continue
            rows.append([pid, r.get("name"), r.get("team"), r.get("pos") if kind == "hitter" else r.get("role"), r.get(nkey)]
                        + [r["values"].get(m["key"]) for m in mets])
        out["rows"][kind] = rows
    if not out["kinds"]:
        return {"ok": False, "reason": "no catalogues", "level": ctx.level, "season": ctx.season}
    return out
