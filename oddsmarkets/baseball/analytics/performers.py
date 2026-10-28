"""
The Bullpen's standings page: top and bottom performers (data/<L>/<S>/performers.json), from that season's
hitters.json and pitchers.json (oddsmarkets/common/performers.py writes the shape; the kit's QKL.leaders draws it).

    build(hitters, pitchers, level, season) -> the document, or None when nobody has qualified

Views: all hitters, then each fielding position (C, 1B, 2B, 3B, SS, CF, corner outfield, DH), starters and relievers,
each on its spec headline set (docs/_design/metrics/baseball.json) with WAR (our model) first. Qualified: the spec's
minimums, prorated by the season's team games over 162: 200 PA for hitters, 300 batters faced for starters, 120 for
relievers (the catalogues' own `qualified` flag is the batting-title rule, stricter than the spec). The teams view comes
from season.json's league block in the page. Pitcher views carry kind "pitcher" so the page links the pitcher pages.
Season to date only: no look-ahead.
"""
from __future__ import annotations

from oddsmarkets.common import performers as P

# QKL.fmtVal codes for the boards
FMT = {"war": "+1", "war_600": "+1", "xwoba_n": "3", "woba": "3", "iso": "3", "barrel_pct": "pct1", "hard_pct": "pct1",
       "bat_speed": "1", "k_pct": "pct1", "bb_pct": "pct1", "chase_pct": "pct1", "sprint_speed": "1", "framing_rate": "pct1",
       "sra": "pct1", "arm": "1", "xfip": "2", "csw_pct": "pct1", "stuff_plus": "0", "pitching_plus": "0", "fb_velo": "1",
       "gb_pct": "pct1", "k_bb_pct": "pct1", "whiff_pct": "pct1", "hr": "0"}
HITTER_GROUPS = [("hitters_all", "all", "All hitters", "hitters", None),
                 ("hitters_C", "c", "Catchers", "catchers", {"C"}),
                 ("hitters_1B", "1b", "First base", "first basemen", {"1B"}),
                 ("hitters_2B", "2b", "Second base", "second basemen", {"2B"}),
                 ("hitters_3B", "3b", "Third base", "third basemen", {"3B"}),
                 ("hitters_SS", "ss", "Shortstops", "shortstops", {"SS"}),
                 ("hitters_CF", "cf", "Centre field", "centre fielders", {"CF"}),
                 ("hitters_LFRF", "of", "Corner outfield", "corner outfielders", {"LF", "RF", "OF"}),
                 ("hitters_DH", "dh", "Designated hitters", "designated hitters", {"DH", "TWP"})]
PITCHER_GROUPS = [("sp", "sp", "Starters", "starters", "SP", 300), ("rp", "rp", "Relievers", "relievers", "RP", 120)]
OURS = "Wins above replacement"
WAR = {"key": "war", "label": "Wins above replacement", "unit": "WAR", "dir": "higher", "fmt": "+1", "ours": OURS,
       "tip": "Wins a player has added over a replacement-level player this season: our model."}
HR = {"key": "hr", "label": "Home runs", "unit": "", "dir": "higher", "fmt": "0", "tip": "Home runs this season."}


def _prorate(cat: dict | None) -> float:
    try:
        g = float((cat or {}).get("team_games") or 162)
    except (TypeError, ValueError):
        g = 162.0
    return max(0.0, min(162.0, g)) / 162.0


def _players(cat: dict | None) -> dict:
    p = (cat or {}).get("players") or {}
    return p if isinstance(p, dict) else {}


def _row(pid, p) -> dict:
    return {"id": str(pid), "name": p.get("name") or "", "team": str(p.get("team") or ""), "v": p.get("values") or {}}


def build(hitters: dict | None, pitchers: dict | None, level: str, season) -> dict | None:
    spec = P.load_spec("baseball")
    views = []
    if (hitters or {}).get("ok"):
        f = _prorate(hitters)
        min_pa = round(200 * f)
        hit = [(pid, p) for pid, p in _players(hitters).items() if isinstance(p, dict) and (P.num(p.get("pa")) or 0) >= 200 * f]
        for gid, key, label, peer, pos in HITTER_GROUPS:
            rows = [_row(pid, p) for pid, p in hit if pos is None or p.get("pos") in pos]
            ms = [WAR] + ([HR] if pos is None else []) + P.spec_metrics(spec, gid, fmt=FMT)
            ms.sort(key=lambda m: 0 if m.get("ours") else 1)
            views.append(P.view(key, label, rows, ms, peer=peer, min_text=f"{min_pa} plate appearances (200 over a full season)"))
    if (pitchers or {}).get("ok"):
        f = _prorate(pitchers)
        for gid, key, label, peer, role, bf in PITCHER_GROUPS:
            rows = [_row(pid, p) for pid, p in _players(pitchers).items()
                    if isinstance(p, dict) and p.get("role") == role and (P.num(p.get("bf")) or 0) >= bf * f]
            ms = [WAR] + P.spec_metrics(spec, gid, fmt=FMT)
            ms.sort(key=lambda m: 0 if m.get("ours") else 1)
            v = P.view(key, label, rows, ms, peer=peer, min_text=f"{round(bf * f)} batters faced ({bf} over a full season)")
            if v:
                v["kind"] = "pitcher"
            views.append(v)
    meta = hitters if (hitters or {}).get("ok") else pitchers
    doc = P.document(views, level=level, season=int(season) if str(season).isdigit() else season,
                     team_games=(meta or {}).get("team_games"), updated_at=(meta or {}).get("updated_at"))
    return doc if doc["views"] else None
