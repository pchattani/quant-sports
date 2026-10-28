"""Player progression for The Quant Campus (CFB, MBB, WBB), on the kit's recipe (oddsmarkets/common/progression.py,
MIGRATION_V4.md "Progression"): `dv` / `dp` / `pg` on the career files' seasons[] rows, a `prog` block per file, and
each level's data/<level>/progression_ref.json.

The career builders (football/build.py and hoops/build.py `career_files`) pass, per season, one record per player:
{"pid", "kind" (CFB: the position; MBB/WBB: the role G / W / B), "gid" (the spec group: cfb_qb, mbb_guards ...), "q"
(meets the group's minimum: CFB the rate minimum, FBS teams only; hoops the catalogue's games and minutes floor),
"values" {metric: value}, "pct" (the catalogue's own percentiles, optional)}. College has no dates of birth, so the
front end compares careers by season or by year in college.
"""
from __future__ import annotations

from typing import Iterable

from oddsmarkets.common import progression as PG

PROG_FILE = "progression_ref.json"
CFB_GROUP = {"QB": "cfb_qb", "RB": "cfb_rb", "WR": "cfb_wr", "TE": "cfb_te", "DL": "cfb_dl", "LB": "cfb_lb", "DB": "cfb_db",
             "K": "cfb_k", "P": "cfb_p"}
HOOPS_ROLE = {"G": "guards", "W": "wings", "B": "bigs"}
# rates already on the season lines that the spec lists in no group of the kind (after its headline and secondary sets)
CFB_EXTRA = {"QB": ("epa_db", "sack_rate", "expl_pass", "ypd", "qb_rush_epa", "epa"), "RB": ("epa_rush", "expl_rush", "stuff_rate", "epa"),
             "WR": ("epa_tgt", "catch_rate", "expl_tgt", "ypt", "epa"), "TE": ("epa_tgt", "catch_rate", "expl_tgt", "ypt", "epa"),
             "DL": ("tfl_pg", "def_int_pg", "hurries_pg", "sacks_pg"), "LB": ("hurries_pg", "def_int_pg", "sacks_pg"),
             "DB": ("sacks_pg", "hurries_pg", "tfl_pg"), "K": ("fga_pg", "fg_long"), "P": ()}
HOOPS_EXTRA = ("value_pg", "value", "efg", "tpar", "ftr", "ast_tov", "drb_pct", "usg", "ortg", "pf100", "min", "pts")


def gid_of(level: str, kind: str | None) -> str | None:
    if not kind:
        return None
    if level == "cfb":
        return CFB_GROUP.get(kind)
    return f"{level}_{HOOPS_ROLE[kind]}" if kind in HOOPS_ROLE else None


def build(level: str, seasons: dict[int, Iterable[dict]]) -> tuple[dict[str, dict[int, dict]], dict, dict]:
    """({pid: {season: {dv, dp, pg}}}, progression_ref.json, the files' prog block)."""
    seasons = {s: list(r) for s, r in seasons.items()}
    have: dict[str, set] = {}
    for recs in seasons.values():
        for r in recs:
            if r.get("kind"):
                have.setdefault(r["kind"], set()).update(k for k, v in (r.get("values") or {}).items() if v is not None)
    keys = {}
    for kind, hv in have.items():
        gid = gid_of(level, kind)
        if gid:
            extra = HOOPS_EXTRA if level != "cfb" else CFB_EXTRA.get(kind, ())
            keys[kind] = PG.deep_keys("college", [gid], hv, extra=extra)
    pb = PG.Builder("college", keys)
    out: dict[str, dict[int, dict]] = {}
    for s, recs in sorted(seasons.items()):
        for r in recs:
            kind = r.get("kind")
            if kind not in keys:
                continue
            out.setdefault(str(r["pid"]), {})[int(s)] = pb.add(int(s), kind, gid_of(level, kind), r.get("values") or {},
                                                              bool(r.get("q")), pct=r.get("pct"))
    pb.finish()
    return out, pb.reference(), pb.prog_block()


def merge(page: dict, seasons_rows: list[dict], rows: dict[int, dict] | None, prog: dict | None) -> None:
    """The progression fields onto a career file's season rows (by season) and its `prog` block, in place."""
    hit = False
    for s in seasons_rows:
        r = (rows or {}).get(int(s.get("season") or 0))
        if r:
            s.update(r)
            hit = True
    if hit and prog:
        page["prog"] = prog
