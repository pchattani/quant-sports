"""
The Rink's league page: top and bottom performers (data/<S>/performers.json), from that season's skaters.json and
goalies.json (oddsmarkets/common/performers.py writes the shape; the kit's QKL.leaders draws it).

    build(skaters, goalies, season) -> the document, or None when neither catalogue has qualified players

Views: all skaters (our value model first, then the league-wide numbers), forwards and defence (each on its spec
headline set, docs/_design/metrics/hockey.json), goalies (GSAx first). Qualified players only: the payloads'
`qualified` flag, which is the spec's floor (250 5v5 minutes over a full season, prorated by team games; goalies a
quarter of the team's minutes). Ice time per game is a usage number, not a performance, so it gets no board. The
teams view comes from season.json's league block in the page. Season to date only: no look-ahead.
"""
from __future__ import annotations

from oddsmarkets.common import performers as P

# QKL.fmtVal codes for the boards
FMT = {"gar": "+1", "gar_60": "+2", "p60": "2", "ixg60_all": "2", "icf60": "1", "adj_xgf_pct": "pct1", "xgf60_rel": "+2",
       "rapm_net": "+2", "rapm_off": "+2", "rapm_def": "+2", "adj_xga60": "2", "pen_diff60": "+2", "g": "0", "p": "0",
       "gsax100": "+2", "gsax": "+1", "sv_pct": "3", "sv_pct_high": "3", "sv_pct_med": "3", "sv_pct_low": "3", "qs_pct": "pct0"}
SKIP = {"toi_gp"}
# the league-wide board for every skater: our value model, then the scoring and chance numbers
ALL = [{"key": "gar_60", "label": "Rink value per 60", "unit": "GAR/60", "ours": "Rink value (GAR / WAR)", "fmt": "+2",
        "tip": "Goals above a replacement-level player per 60 minutes, from our value model."},
       {"key": "gar", "label": "Goals above replacement", "unit": "GAR", "ours": "Rink value (GAR / WAR)", "fmt": "+1",
        "tip": "Goals above a replacement-level skater this season: 5v5 impact, power play, penalty kill, finishing and penalties."},
       {"key": "p", "label": "Points", "unit": "", "fmt": "0", "tip": "Goals plus assists, all situations."},
       {"key": "g", "label": "Goals", "unit": "", "fmt": "0", "tip": "Goals, all situations."},
       {"key": "p60", "label": "Points per 60", "unit": "per 60", "fmt": "2", "tip": "Goals plus assists per 60 minutes, all situations."},
       {"key": "ixg60_all", "label": "Individual xG per 60", "unit": "per 60", "ours": "Our expected-goals model", "fmt": "2",
        "tip": "Expected goals from the player's own shots per 60 minutes, all situations."},
       {"key": "adj_xgf_pct", "label": "Adjusted xG share (5v5)", "unit": "", "ours": "Our expected-goals model", "fmt": "pct1",
        "tip": "The share of 5v5 expected goals while on the ice, adjusted for score and venue."}]


def _rows(cat: dict | None, groups: set[str] | None) -> list[dict]:
    out = []
    for pid, p in ((cat or {}).get("players") or {}).items():
        if not isinstance(p, dict) or not p.get("qualified"):
            continue
        if groups is not None and p.get("group") not in groups:
            continue
        out.append({"id": str(pid), "name": p.get("name") or "", "team": p.get("team") or "", "v": p.get("values") or {}})
    return out


def build(skaters: dict | None, goalies: dict | None, season) -> dict | None:
    spec = P.load_spec("hockey")
    tg = (skaters or {}).get("team_games") or (goalies or {}).get("team_games")
    sk_min = "250 minutes at 5v5 over a full season, prorated by team games"
    views = [
        P.view("all", "All skaters", _rows(skaters, {"F", "D"}), ALL, peer="skaters", min_text=sk_min),
        P.view("forwards", "Forwards", _rows(skaters, {"F"}), P.spec_metrics(spec, "forwards", fmt=FMT, skip=SKIP), peer="forwards", min_text=sk_min),
        P.view("defence", "Defence", _rows(skaters, {"D"}), P.spec_metrics(spec, "defence", fmt=FMT, skip=SKIP), peer="defencemen", min_text=sk_min),
        P.view("goalies", "Goalies", _rows(goalies, None), P.spec_metrics(spec, "goalies", fmt=FMT, skip=SKIP), peer="goalies",
               min_text="a quarter of the team's minutes in net"),
    ]
    doc = P.document(views, season=int(season) if str(season).isdigit() else season, team_games=tg,
                     updated_at=(skaters or {}).get("updated_at") or (goalies or {}).get("updated_at"))
    return doc if doc["views"] else None
