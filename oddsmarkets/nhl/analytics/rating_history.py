"""The Rink's weekly team-rating history: <S>/rating_history.json, the team-strength rating (goals a game against an
average club, models/team_strength.py) as it stood going into each week of the season.

Each point is a refit of the same ridge on the season's team-game rows dated strictly before that Monday, pulled toward
the same preseason prior the build's own fit uses (chained from the earlier seasons' end-of-season ratings), so a point
uses nothing played on or after its date: no look-ahead. Nothing is fetched: the rows come from the season store the
build already reads (models/_cdata.team_games). Builder B's season-to-date goalie table is left out of the weekly fits
(it covers the whole season so far); the goalie term comes from the fit's own decayed sums through the date instead.
On the current season that moves a club's league rank by at most one place against the published rating (measured
10 Nov 2026), under the three places a "rating move" fact needs (common/follow.py _f_rating_move).

    {"ok": true, "season": 20262027, "units": "goals a game against an average club", "asof": "2026-11-10",
     "weeks": ["2026-10-05", ...]                 the Mondays (each point is the rating going into that week)
     "teams": {"TOR": [-0.21, ...]},              the rating at each Monday
     "ranks": {"TOR": [18, ...]}}                 the league rank at each Monday (1 = best)

    build(season, today, rd=None) -> payload     rd: the build's own team_strength result (its "prior" is reused)

The follow cards (follow_build.py) read the ranks for the "rating move" fact; the card's latest point is the
published rating's rank.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

UNITS = "goals a game against an average club"


def mondays(first: date, today: date) -> list[date]:
    """Every Monday after the season's first game day, through today."""
    d = first + timedelta(days=(7 - first.weekday()) % 7 or 7)
    out = []
    while d <= today:
        out.append(d)
        d += timedelta(days=7)
    return out


def _prior(season: int, p: dict, teams: list[str]) -> dict:
    """The preseason prior as team_strength.for_season builds it (without the player composition it also attaches)."""
    from oddsmarkets.nhl.models import _cdata as D
    from oddsmarkets.nhl.models import team_strength as TS
    on_disk = set(D.seasons_on_disk())
    chain = [s for s in (D.sid(D.start_year(season) - k) for k in range(4, 0, -1)) if s in on_disk]
    ch = TS.season_chain(chain, prm=p) if chain else {"ends": {}}
    book: dict = {}
    for s in sorted(ch["ends"]):
        TS.update_goalie_book(book, ch["ends"][s])
    return TS.preseason_prior(ch["ends"].get(D.prev_season(season)), season, p, book, teams)


def build(season: int, today: date, rd: dict | None = None) -> dict:
    from oddsmarkets.nhl.models import _cdata as D
    from oddsmarkets.nhl.models import team_strength as TS
    season = int(season)
    tg = D.team_games(season)
    if tg is None or not len(tg):
        return {"ok": False, "season": season, "reason": "no games in the store yet"}
    p = TS.params()
    teams = sorted(D.teams_for(season))
    prior = (rd or {}).get("prior") if isinstance(rd, dict) and isinstance((rd or {}).get("prior"), dict) else None
    if prior is None:
        prior = _prior(season, p, teams)
    first = pd.Timestamp(tg["date"].min()).date()
    weeks = mondays(first, today)
    hist: dict[str, list] = {t: [] for t in teams}
    ranks: dict[str, list] = {t: [] for t in teams}
    kept = []
    for m in weeks:
        r = TS.fit(tg, season, m.isoformat(), prior, p, teams=teams).as_dict().get("teams") or {}
        col = {t: float(v["net"]) for t, v in r.items() if t in hist and v.get("net") is not None}
        if len(col) < len(teams) // 2:
            continue
        order = sorted(col, key=lambda t: -col[t])
        rk = {t: i + 1 for i, t in enumerate(order)}
        kept.append(m.isoformat())
        for t in teams:
            hist[t].append(round(col[t], 3) if t in col else None)
            ranks[t].append(rk.get(t))
    return {"ok": True, "season": season, "units": UNITS, "asof": today.isoformat(), "weeks": kept,
            "teams": hist, "ranks": ranks}


if __name__ == "__main__":  # python -m oddsmarkets.nhl.analytics.rating_history 20262027 [YYYY-MM-DD]
    import json
    import sys
    s = int(sys.argv[1])
    t = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
    print(json.dumps(build(s, t))[:2000])
