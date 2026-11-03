"""
Hitter and pitcher catalogues for a level with no pitch table (Double-A, High-A, Single-A).

Baseball Savant does not publish those levels, so the pages use the same catalogue shape as MLB, filled from
the official season counting lines (analytics/mlbapi.py, already cached). Statcast and model columns are left
out: a column with no values is not a column. wOBA uses the default linear weights.
"""
from __future__ import annotations

from typing import Any

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import catalog as CT
from oddsmarkets.baseball.analytics.context import SeasonContext
from oddsmarkets.baseball.models.projections import WOBA_DEFAULT

H_KEYS = ("g", "pa", "ab", "h", "b1", "b2", "b3", "hr", "bb", "ibb", "hbp", "so", "sf", "sh", "gidp",
          "avg", "obp", "slg", "ops", "iso", "babip", "woba", "k_pct", "bb_pct", "bb_k", "hr_pa", "xbh_pa", "hbp_pct")
P_KEYS = ("g", "gs", "w", "l", "sv", "ip", "bf", "h", "hr", "bb", "ibb", "hbp", "so", "r",
          "ra9", "whip", "k_pct", "bb_pct", "k_bb_pct", "k9", "bb9", "hr9", "avg_against", "obp_against", "fip")
NOTE = ("Official counting stats. Pitch tracking is not published at this level, so the Statcast and model "
        "columns are not on this page.")


def _rate(num: float, den: float) -> float | None:
    return (num / den) if den else None


def _age(ctx: SeasonContext, pid: str, line: dict) -> float | None:
    info = ctx.players.get(pid) or {}
    return an.age_on(info.get("dob"), ctx.season) or (float(line["age"]) if line.get("age") else None)


def _rows(ctx: SeasonContext, lines: dict, kind: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for pid, line in lines.items():
        built = _hitter(line) if kind == "hitter" else _pitcher(line)
        if not built:
            continue
        v, n, sample = built
        info = ctx.players.get(pid) or {}
        rows[pid] = {"name": ctx.name(pid), "team": line.get("team"), "pos": info.get("pos"),
                     "bats": info.get("bats"), "throws": info.get("throws"), "age": _age(ctx, pid, line),
                     "pa" if kind == "hitter" else "bf": int(sample),
                     "qualified": False, "values": v, "n": n}
    return rows


def _hitter(line: dict) -> tuple[dict, dict, float] | None:
    pa, ab = float(line.get("pa") or 0), float(line.get("ab") or 0)
    if pa < 1 or ab < 0:
        return None
    h = float(line.get("h") or 0)
    b2, b3, hr = float(line.get("d") or 0), float(line.get("t") or 0), float(line.get("hr") or 0)
    b1 = max(h - b2 - b3 - hr, 0.0)
    bb, ibb = float(line.get("bb") or 0), float(line.get("ibb") or 0)
    hbp, so = float(line.get("hbp") or 0), float(line.get("so") or 0)
    sf, sh = float(line.get("sf") or 0), float(line.get("sh") or 0)
    w = WOBA_DEFAULT
    w_den = ab + bb + hbp + sf
    w_num = w["BB"] * bb + w["HBP"] * hbp + w["1B"] * b1 + w["2B"] * b2 + w["3B"] * b3 + w["HR"] * hr
    avg, obp = _rate(h, ab), _rate(h + bb + hbp, w_den)
    slg = _rate(b1 + 2 * b2 + 3 * b3 + 4 * hr, ab)
    v = {"g": line.get("g"), "pa": pa, "ab": ab, "h": h, "b1": b1, "b2": b2, "b3": b3, "hr": hr,
         "bb": max(bb - ibb, 0.0), "ibb": ibb, "hbp": hbp, "so": so, "sf": sf, "sh": sh, "gidp": line.get("gidp"),
         "avg": avg, "obp": obp, "slg": slg,
         "ops": (obp + slg) if obp is not None and slg is not None else None,
         "iso": (slg - avg) if slg is not None and avg is not None else None,
         "babip": _rate(h - hr, ab - so - hr + sf), "woba": _rate(w_num, w_den),
         "k_pct": _rate(so, pa), "bb_pct": _rate(bb, pa), "bb_k": _rate(bb, so),
         "hr_pa": _rate(hr, pa), "xbh_pa": _rate(b2 + b3 + hr, pa), "hbp_pct": _rate(hbp, pa)}
    return v, {"pa": int(pa), "bip": int(max(ab - so - hr + sf, 0))}, pa


def _pitcher(line: dict) -> tuple[dict, dict, float] | None:
    bf, outs = float(line.get("bf") or 0), float(line.get("outs") or 0)
    if bf < 1 or outs <= 0:
        return None
    ip = outs / 3.0
    h, hr = float(line.get("h") or 0), float(line.get("hr") or 0)
    bb, ibb = float(line.get("bb") or 0), float(line.get("ibb") or 0)
    hbp, so = float(line.get("hbp") or 0), float(line.get("so") or 0)
    r = float(line.get("r") or 0)
    ab = max(bf - bb - hbp, 0.0)
    k_pct, bb_pct = _rate(so, bf), _rate(bb, bf)
    v = {"g": line.get("g"), "gs": line.get("gs"), "w": line.get("w"), "l": line.get("l"), "sv": line.get("sv"),
         "ip": ip, "bf": bf, "h": h, "hr": hr, "bb": max(bb - ibb, 0.0), "ibb": ibb, "hbp": hbp, "so": so, "r": r,
         "ra9": _rate(r * 9.0, ip), "whip": _rate(bb + h, ip),
         "k_pct": k_pct, "bb_pct": bb_pct,
         "k_bb_pct": (k_pct - bb_pct) if k_pct is not None and bb_pct is not None else None,
         "k9": _rate(so * 9.0, ip), "bb9": _rate(bb * 9.0, ip), "hr9": _rate(hr * 9.0, ip),
         "avg_against": _rate(h, ab), "obp_against": _rate(h + bb + hbp, bf),
         "fip": _rate(13.0 * hr + 3.0 * (bb + hbp) - 2.0 * so, ip)}
    if v["fip"] is not None:
        v["fip"] += 3.10
    return v, {"bf": int(bf)}, bf


def _finish(ctx: SeasonContext, rows: dict[str, dict], metrics: list[dict], keys: tuple[str, ...], kind: str,
            sample_key: str, per_game: float) -> dict:
    use = [m for m in metrics if m["key"] in keys]
    tg = ctx.team_games() or 1
    for r in rows.values():
        r["qualified"] = r[sample_key] >= per_game * tg
    role = {p: CT.POS_GROUP.get(r.get("pos") or "", "DH" if kind == "hitter" else "P") for p, r in rows.items()}
    floor = max(50, per_game * tg) if kind == "hitter" else 50
    reference = [p for p, r in rows.items() if r[sample_key] >= floor]
    if len(reference) < 20:
        reference = sorted(rows, key=lambda p: -rows[p][sample_key])[:max(20, len(rows) // 3)]
    floors = {"pa": 50, "bip": 25, "bf": 50}
    means = CT.finish(ctx, rows, use, reference, role, floors)
    return {**CT.season_meta(ctx), "kind": kind, "source": "statsapi", "note": NOTE,
            "metrics": [an.public_metric(m) for m in use], "players": rows,
            "reference": {"rule": "official season lines", "n": len(reference), "means": {k: an.rnd(v, 4) for k, v in means.items()}},
            "floors": floors, "roles": sorted(set(role.values()))}


def hitters_from_lines(ctx: SeasonContext, metrics: list[dict]) -> dict | None:
    from oddsmarkets.baseball.analytics import mlbapi
    lines = mlbapi.season_lines(ctx.level, ctx.season, "hitting") or {}
    rows = _rows(ctx, lines, "hitter")
    if len(rows) < 10:
        return None
    return _finish(ctx, rows, metrics, H_KEYS, "hitter", "pa", 3.1)


def pitchers_from_lines(ctx: SeasonContext, metrics: list[dict]) -> dict | None:
    from oddsmarkets.baseball.analytics import mlbapi
    lines = mlbapi.season_lines(ctx.level, ctx.season, "pitching") or {}
    rows = _rows(ctx, lines, "pitcher")
    if len(rows) < 10:
        return None
    return _finish(ctx, rows, metrics, P_KEYS, "pitcher", "bf", 1.0)
