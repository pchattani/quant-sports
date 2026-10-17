"""
Lines: forward trios and defence pairs at 5v5 — time together and on-ice xG share, shrunk.

From the enriched 5v5 stints, each side's skaters are split by position group (store positions; F unless D):
a side with exactly three forwards and two defencemen contributes its trio and its pair. Per (team, unit):
TOI together, on-ice xGF / xGA (and CF / CA, GF / GA), raw shares, and

    xgf_pct_shrunk = (xGF + m * p_team) / (xGF + xGA + m)

with p_team the team's 5v5 xGF% and m = the pseudo-xG of stabilise.py's "xgf_pct" constant (k in seconds times
the league's 5v5 xG rate per second, both sides): a line regresses to its team's share until its xG sample is
comparable with k. `for_season` lists units with at least MIN_TOI minutes (forwards and pairs, sorted by team
and TOI).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _io, _stints

MODEL_VERSION = "nhllines-1"
MIN_TOI = 20.0           # minutes


def units(st: pd.DataFrame, group: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(forwards, pairs) frames: team, ids (tuple), toi (s), xgf, xga, cf, ca, gf, ga."""
    s = st[st["strength"] == "5v5"]
    fw, dp = [], []
    gmap = group.to_dict()
    for side in ("h", "a"):
        o = "a" if side == "h" else "h"
        slots = _io.SLOTS_H[:5] if side == "h" else _io.SLOTS_A[:5]
        P = s[slots].to_numpy(float)
        ok = np.isfinite(P).all(axis=1)
        P = P[ok]
        sub = s[ok]
        G = np.vectorize(lambda p: gmap.get(int(p), "F"), otypes=[object])(P) if len(P) else np.zeros((0, 5), object)
        isd = G == "D"
        good = isd.sum(axis=1) == 2
        P, isd, sub = P[good], isd[good], sub[good]
        order = np.argsort(isd, axis=1, kind="stable")              # forwards first, then the two D
        Ps = np.take_along_axis(P, order, axis=1)
        f3 = np.sort(Ps[:, :3], axis=1)
        d2 = np.sort(Ps[:, 3:], axis=1)
        base = {"team": sub["home_team" if side == "h" else "away_team"].to_numpy(object), "toi": sub["dur"].to_numpy(float),
                "xgf": sub[f"{side}_xg"].to_numpy(float), "xga": sub[f"{o}_xg"].to_numpy(float),
                "cf": sub[f"{side}_cf"].to_numpy(float), "ca": sub[f"{o}_cf"].to_numpy(float),
                "gf": sub[f"{side}_gf"].to_numpy(float), "ga": sub[f"{o}_gf"].to_numpy(float)}
        fw.append(pd.DataFrame({**base, "p1": f3[:, 0], "p2": f3[:, 1], "p3": f3[:, 2]}))
        dp.append(pd.DataFrame({**base, "p1": d2[:, 0], "p2": d2[:, 1]}))
    f = pd.concat(fw, ignore_index=True).groupby(["team", "p1", "p2", "p3"]).sum().reset_index() if fw else pd.DataFrame()
    d = pd.concat(dp, ignore_index=True).groupby(["team", "p1", "p2"]).sum().reset_index() if dp else pd.DataFrame()
    return f, d


def finish(u: pd.DataFrame, team5: pd.DataFrame, m: float, names: dict, k_ids: list[str], min_toi: float) -> list[dict]:
    if not len(u):
        return []
    u = u.copy()
    u["toi"] = u["toi"] / 60.0
    u = u[u["toi"] >= min_toi]
    p_team = u["team"].map(team5["xgf_pct"]).fillna(0.5).to_numpy(float)
    xf, xa = u["xgf"].to_numpy(float), u["xga"].to_numpy(float)
    u["xgf_pct"] = xf / np.where(xf + xa > 0, xf + xa, np.nan)
    u["xgf_pct_shrunk"] = (xf + m * p_team) / (xf + xa + m)
    u["cf_pct"] = u["cf"] / (u["cf"] + u["ca"]).where(u["cf"] + u["ca"] > 0)
    u["gf_pct"] = u["gf"] / (u["gf"] + u["ga"]).where(u["gf"] + u["ga"] > 0)
    u["team_xgf_pct"] = p_team
    u["xgf60"] = 3600.0 * xf / (60.0 * u["toi"])
    u["xga60"] = 3600.0 * xa / (60.0 * u["toi"])
    u = u.sort_values(["team", "toi"], ascending=[True, False])
    out = []
    for r in u.to_dict("records"):
        ids = [int(r[c]) for c in k_ids]
        rec = {"team": r["team"], "players": [str(i) for i in ids], "names": [names.get(i, str(i)) for i in ids]}
        for c in ("toi", "xgf", "xga", "xgf60", "xga60", "xgf_pct", "xgf_pct_shrunk", "team_xgf_pct", "cf", "ca", "cf_pct", "gf",
                  "ga", "gf_pct"):
            rec[c] = r[c]
        out.append(rec)
    return _io.clean(out, 4)


def season_lines(season: int, min_toi: float = MIN_TOI, use_cache: bool = True) -> dict:
    from oddsmarkets.nhl.models import onice, stabilise
    st = _stints.for_season(season, use_cache)
    if st is None or not len(st):
        return {"ok": False, "reason": "no stints"}
    ev = _io.events(season)
    pos = _io.players(season, ev)
    f, d = units(st, pos["group"])
    tt = onice.team_totals(st)
    t5 = tt.xs("5v5", level="role") if "5v5" in tt.index.get_level_values("role") else pd.DataFrame()
    team5 = pd.DataFrame({"xgf_pct": t5["xgf"] / (t5["xgf"] + t5["xga"])}) if len(t5) else pd.DataFrame({"xgf_pct": []})
    rate = float((t5["xgf"].sum() + t5["xga"].sum()) / max(t5["toi"].sum(), 1e-9)) if len(t5) else 0.0015
    k_sec = stabilise.shrink_k("xgf_pct")
    m = k_sec * rate                          # both sides' xG per second of the team's ice time x k
    names = {int(p): n for p, n in pos["name"].items()} if "name" in pos else {}
    return {"ok": True, "season": _io.sid(season), "min_toi": min_toi, "pseudo_xg": m,
            "forwards": finish(f, team5, m, names, ["p1", "p2", "p3"], min_toi),
            "pairs": finish(d, team5, m, names, ["p1", "p2"], min_toi)}


def for_season(season: int, use_cache: bool = True) -> dict:
    from oddsmarkets.nhl.models import stabilise, xg
    season = _io.sid(season)
    if not _io.stints_path(season).exists():
        return {"ok": False, "reason": "no stints for this season"}
    f = xg.current_fit() or {}
    key = _io.file_key(_io.events_path(season), _io.stints_path(season), _io.store_path(season), MODEL_VERSION,
                       f.get("key"), f.get("platt"), stabilise.shrink_k("xgf_pct"))
    return _io.cached("lines", str(season), key, lambda: season_lines(season, MIN_TOI, use_cache), use_cache)
