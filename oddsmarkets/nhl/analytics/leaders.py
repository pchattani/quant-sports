"""
leaders.json, lab.json, lines.json and awards.json.

leaders.json: top 25 per headline metric among qualified skaters / goalies (direction-aware), and team leaders.
lab.json: the catalogues column-oriented per kind ({"cols", "ids", "data": {key: [...]}} for skaters, goalies, teams
and lines) for the scatter / filter lab.
lines.json: every 5v5 forward line and defence pair with at least LINE_MIN_TOI minutes (TOI, games, on-ice CF%,
xGF / xGA per 60, xGF%, goals), league-wide.
awards.json: builder C's award races when it answers, the verified winners of the season, and model-free
leaderboards for each trophy's usual criteria (Rink value, points, goals, GSAx, rookies).
"""
from __future__ import annotations

from oddsmarkets.nhl import analytics as an
from oddsmarkets.nhl.analytics import adapters, tables
from oddsmarkets.nhl.analytics.teams import line_row

HEADLINE_S = ["p", "g", "a", "p60", "ixg", "ixg60", "gax", "xgf_pct", "xgf_pct_rel", "cf_pct", "rapm_net", "rapm_off", "rapm_def", "gar",
              "war", "hits", "blocks", "fo_pct", "pen_diff60", "edge_max_speed", "edge_shot_speed", "pp_p", "toi_gp"]
HEADLINE_G = ["gsax", "gsax60", "sv_pct", "gsax_high", "w", "qs_pct", "gar", "gaa"]
INDEX_S = ["p", "g", "ixg", "gax", "gar", "xgf_pct", "rapm_net"]
INDEX_G = ["gsax", "sv_pct", "gar"]
LINE_MIN_TOI = 20.0
COUNTING = {"g", "a", "p", "ixg", "hits", "blocks", "pp_p", "w", "gsax", "gar", "war", "gax", "gsax_high", "edge_max_speed", "edge_shot_speed"}


def top(cat: dict | None, key: str, n: int = 25, qualified: bool = True) -> list[list]:
    if not cat or not cat.get("players"):
        return []
    m = next((x for x in cat.get("metrics") or [] if x["key"] == key), None)
    if m is None:
        return []
    counting = key in COUNTING                                  # totals: everyone ranks; rates: the qualified pool
    cand = [(p, r["values"].get(key), r) for p, r in cat["players"].items()
            if r["values"].get(key) is not None and (counting or r.get("qualified") or not qualified)]
    cand.sort(key=lambda x: x[1], reverse=not m.get("lower"))
    return [[p, v, r.get("name"), r.get("team")] for p, v, r in cand[:n]]


def build(ctx, sk: dict | None, gk: dict | None, teams_payload: dict | None) -> dict | None:
    if not (sk or {}).get("ok") and not (gk or {}).get("ok"):
        return None
    out = {"ok": True, "season": ctx.season, "updated_at": an.now(), "cols": ["id", "value", "name", "team"], "skaters": {}, "goalies": {},
           "teams": {}}
    lab = {m["key"]: m for m in (sk or {}).get("metrics") or []}
    for k in HEADLINE_S:
        if k in lab:
            out["skaters"][k] = {"label": lab[k]["label"], "fmt": lab[k]["fmt"], "lower": lab[k]["lower"], "rows": top(sk, k)}
    labg = {m["key"]: m for m in (gk or {}).get("metrics") or []}
    for k in HEADLINE_G:
        if k in labg:
            out["goalies"][k] = {"label": labg[k]["label"], "fmt": labg[k]["fmt"], "lower": labg[k]["lower"], "rows": top(gk, k)}
    tp = (teams_payload or {}).get("teams") or {}
    for k, lower in (("rating", False), ("off5", False), ("def5", True), ("pp", False), ("pk", True), ("goalie", False), ("xgf_pct5", False)):
        vals = [(t, (v.get("units") or {}).get(k)) for t, v in tp.items() if (v.get("units") or {}).get(k) is not None]
        vals.sort(key=lambda x: x[1], reverse=not lower)
        out["teams"][k] = [[t, v] for t, v in vals]
    return out


def index_leaders(sk: dict | None, gk: dict | None) -> dict:
    out = {}
    for k in INDEX_S:
        rows = top(sk, k, 10)
        if rows:
            out[f"s_{k}"] = [[r[0], r[1]] for r in rows]
    for k in INDEX_G:
        rows = top(gk, k, 10)
        if rows:
            out[f"g_{k}"] = [[r[0], r[1]] for r in rows]
    return out


def _columns(cat: dict | None) -> dict | None:
    if not cat or not cat.get("players"):
        return None
    keys = [m["key"] for m in cat.get("metrics") or []]
    ids = list(cat["players"])
    P = cat["players"]
    data = {k: [P[p]["values"].get(k) for p in ids] for k in keys}
    return {"cols": keys, "ids": ids, "name": [P[p].get("name") for p in ids], "team": [P[p].get("team") for p in ids],
            "pos": [P[p].get("pos") for p in ids], "qualified": [bool(P[p].get("qualified")) for p in ids],
            "age": [P[p].get("age") for p in ids], "data": data,
            "labels": {m["key"]: [m["label"], m["fmt"], m["lower"], m["group"]] for m in cat.get("metrics") or []}}


def lab(ctx, sk: dict | None, gk: dict | None, teams_payload: dict | None, lines_payload: dict | None) -> dict | None:
    out = {"ok": True, "season": ctx.season, "updated_at": an.now(), "skaters": _columns(sk), "goalies": _columns(gk)}
    tp = (teams_payload or {}).get("teams") or {}
    if tp:
        keys = sorted({k for v in tp.values() for k, x in ((v.get("units") or {}).items()) if isinstance(x, (int, float)) and not isinstance(x, bool)})
        ids = sorted(tp)
        out["teams"] = {"cols": keys, "ids": ids, "data": {k: [(tp[t].get("units") or {}).get(k) for t in ids] for k in keys}}
    lp = (lines_payload or {})
    for kind in ("forwards", "pairs"):
        rows = lp.get(kind) or []
        if rows:
            cols = ["toi", "games", "xgf", "xga", "xgf_pct", "cf_pct", "gf", "ga", "xgf60", "xga60"]
            out[f"lines_{kind}"] = {"cols": cols, "ids": ["-".join(r["ids"]) for r in rows], "team": [r["team"] for r in rows],
                                    "names": [r["names"] for r in rows], "data": {c: [r.get(c) for r in rows] for c in cols}}
    if not out.get("skaters") and not out.get("goalies"):
        return None
    return out


def lines(ctx, sk: dict | None) -> dict | None:
    C = tables.combos(ctx)
    if C is None or not len(C):
        return None
    names = {p: r.get("name") for p, r in ((sk or {}).get("players") or {}).items()}
    for p in {i for k in C["key"] for i in k.split("-")}:
        names.setdefault(p, ctx.player_name(p) or p)
    out = {"ok": True, "season": ctx.season, "updated_at": an.now(), "min_toi": LINE_MIN_TOI, "forwards": [], "pairs": []}
    for kind, key in (("F", "forwards"), ("D", "pairs")):
        K = C[(C["kind"] == kind) & (C["toi"] >= LINE_MIN_TOI * 60)].sort_values("toi", ascending=False)
        for r in K.itertuples(index=False):
            row = line_row(r.key.split("-"), r, names)
            row["team"] = r.team
            out[key].append(row)
    model = adapters.model_lines(ctx)
    if model:
        out["model"] = {k: v for k, v in model.items() if k not in ("ok",)}
    return out


AWARDS = (("hart", "Hart Trophy", "Most valuable player"), ("vezina", "Vezina Trophy", "Best goaltender"),
          ("norris", "Norris Trophy", "Best defenceman"), ("calder", "Calder Trophy", "Best rookie"),
          ("ross", "Art Ross Trophy", "Most points"), ("richard", "Maurice Richard Trophy", "Most goals"),
          ("selke", "Frank J. Selke Trophy", "Best defensive forward"))


def awards(ctx, sk: dict | None, gk: dict | None, model: dict | None) -> dict | None:
    if not (sk or {}).get("ok"):
        return None
    P = (sk or {}).get("players") or {}
    G = (gk or {}).get("players") or {}

    def board(rows, key, n=10, filt=None, src=P):
        c = [(p, r["values"].get(key), r) for p, r in src.items() if r["values"].get(key) is not None and (filt is None or filt(p, r))]
        c.sort(key=lambda x: -x[1])
        return [[p, r.get("name"), r.get("team"), v] for p, v, r in c[:n]]
    rookies = _rookies(ctx, P)
    boards = {
        "hart": board(P, "gar") or board(P, "p"),
        "vezina": board(G, "gsax", src=G),
        "norris": board(P, "gar", filt=lambda p, r: r.get("group") == "D") or board(P, "p", filt=lambda p, r: r.get("group") == "D"),
        "calder": board(P, "p", filt=lambda p, r: p in rookies),
        "ross": board(P, "p"), "richard": board(P, "g"),
        "selke": board(P, "rapm_def", filt=lambda p, r: r.get("group") == "F" and (r.get("gp") or 0) >= 20)
        or board(P, "xga60_rel", filt=lambda p, r: r.get("group") == "F" and (r.get("gp") or 0) >= 20),
    }
    winners = adapters.award_winners(ctx.season)
    races = (model or {}).get("races") if model else None
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "awards": [{"key": k, "name": n, "desc": d} for k, n, d in AWARDS],
            "races": races, "basis": (model or {}).get("basis"), "reasons": (model or {}).get("reasons"), "winners": winners or None, "boards": boards, "board_cols": ["id", "name", "team", "value"],
            "rookies": len(rookies), "model_note": None if races else "award model not available: boards rank the usual criteria"}


def _rookies(ctx, P: dict) -> set[str]:
    """Players in their first NHL season (no regular-season games in any earlier season on disk, or the store's
    rookie flag)."""
    out = set()
    for p in P:
        info = ctx.players.get(p) or {}
        if info.get("rookie") is True:
            out.add(p)
    if out:
        return out
    prev = an.data_root() / str(an.prev_season(ctx.season)) / "skaters.json"
    pv = an.read_json(prev) or {}
    if not pv.get("players"):
        return set()
    return {p for p in P if p not in pv["players"] and (an.age_on((ctx.players.get(p) or {}).get("dob"), ctx.season) or 30) < 26}
