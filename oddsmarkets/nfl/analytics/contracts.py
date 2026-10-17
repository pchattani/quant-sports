"""
Contracts and cap hits for the trade simulator and the team pages: nflverse's `contracts` release
(historical_contracts.parquet, "OverTheCap contract data, accessed with nflreadr::load_contracts()").

PUBLICATION IS OFF BY DEFAULT. The data are OverTheCap's. nflverse-data is CC-BY 4.0, but nflverse cannot license
what it does not own, and OverTheCap's terms and conditions (overthecap.com/terms-and-conditions, read 15 Oct 2026)
say that its content is for individual, informational use; that "no data is allowed to be used by or provided to any
websites, internet publications, media outlets or other blogs for the purpose of providing comprehensive information
on professional football contracts, rosters, or player valuations unless contracted by OTC to do so"; and that
derivative works and systematic retrieval need its written consent. A public trade simulator that shows every
player's cap hit next to a player valuation is that use. So the build reads the file only when GRIDIRON_CONTRACTS=1
(or `build_gridiron.py --contracts`), which should be set only once OverTheCap has given permission or a licence;
until then the pages say that cap and contracts are not checked, and why (`NOT_PUBLISHED`).

When enabled:
  table(season)   {gsis_id: {"cap_hit" ($M, that season's cap number), "team" (abbr), "end" (last contract year:
                  year_signed + years - 1), "years_left" (end - season + 1), "apy" ($M), "contract_year" (end ==
                  season)}} for the players whose active contract has a row for the season.
  season_cap()    the season's salary cap ($M): the median of cap_number / cap_percent over that season's rows.
  team_totals()   {team: sum of the listed cap numbers} (dead money, carry-over and the offseason top-51 rule are not
                  modelled: an approximation, said so on the page).
The file is fetched by `scripts/nfl_fetch.py --releases contracts` (not part of "all").
"""
from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

from oddsmarkets.nfl import analytics as an

logger = logging.getLogger(__name__)

CREDIT = "Contract data from OverTheCap.com via nflverse (nflreadr::load_contracts)."
NOT_PUBLISHED = ("Cap hits and contracts are not shown or checked: the only source we have (OverTheCap, via nflverse) does not "
                 "permit republishing its contract data on a website without OverTheCap's consent. Trades are judged on "
                 "on-field value only.")
_FORCE: bool | None = None

# OverTheCap names clubs by nickname; nflverse abbreviations.
NICK = {"49ers": "SF", "Bears": "CHI", "Bengals": "CIN", "Bills": "BUF", "Broncos": "DEN", "Browns": "CLE", "Buccaneers": "TB",
        "Cardinals": "ARI", "Chargers": "LAC", "Chiefs": "KC", "Colts": "IND", "Commanders": "WAS", "Cowboys": "DAL",
        "Dolphins": "MIA", "Eagles": "PHI", "Falcons": "ATL", "Giants": "NYG", "Jaguars": "JAX", "Jets": "NYJ", "Lions": "DET",
        "Packers": "GB", "Panthers": "CAR", "Patriots": "NE", "Raiders": "LV", "Rams": "LA", "Ravens": "BAL", "Saints": "NO",
        "Seahawks": "SEA", "Steelers": "PIT", "Texans": "HOU", "Titans": "TEN", "Vikings": "MIN", "Redskins": "WAS",
        "Football Team": "WAS"}


def set_enabled(flag: bool | None) -> None:
    """Override the environment switch (the build's --contracts flag; tests)."""
    global _FORCE
    _FORCE = flag


def enabled() -> bool:
    if _FORCE is not None:
        return bool(_FORCE)
    return os.environ.get("GRIDIRON_CONTRACTS", "").strip() in ("1", "true", "yes")


def team_abbr(name: Any) -> str | None:
    s = an.sid(name)
    if not s:
        return None
    if s in NICK:
        return NICK[s]
    if s.isupper() and len(s) <= 3:
        return {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "LVR": "LV"}.get(s, s)
    return None


def _frame():
    from oddsmarkets.nfl.analytics.context import load_release
    return load_release("contracts", None)


def table(season: int, df=None) -> dict[str, dict]:
    """{gsis_id: {cap_hit, team, end, years_left, apy, contract_year}} (see the module docstring); {} when disabled or
    the file is not on disk."""
    if df is None:
        if not enabled():
            return {}
        df = _frame()
    if df is None or not len(df):
        return {}
    out: dict[str, dict] = {}
    act = df[df["is_active"].astype(bool)] if "is_active" in df else df
    S = str(int(season))
    for r in act.to_dict("records"):
        pid = an.sid(r.get("gsis_id"))
        if not pid:
            continue
        hist = r.get("season_history")
        row = None
        if hist is not None:
            for h in list(hist):
                if isinstance(h, dict) and str(h.get("year")) == S:
                    row = h
                    break
        if row is None:
            continue
        ys, yrs = an.inum(r.get("year_signed")), an.inum(r.get("years"))
        end = ys + yrs - 1 if ys is not None and yrs else None
        out[pid] = {"cap_hit": an.rnd(an.fnum(row.get("cap_number")), 3), "cap_pct": an.fnum(row.get("cap_percent")),
                    "team": team_abbr(row.get("team")) or team_abbr(r.get("team")), "end": end,
                    "years_left": (end - int(season) + 1) if end is not None else None, "apy": an.rnd(an.fnum(r.get("apy")), 3),
                    "contract_year": end == int(season) if end is not None else None}
    return out


def season_cap(tab: dict[str, dict]) -> float | None:
    """The season's cap ($M): median cap_hit / cap_pct over rows with both (OverTheCap's cap_percent is of that cap)."""
    xs = [v["cap_hit"] / v["cap_pct"] for v in tab.values() if v.get("cap_hit") and v.get("cap_pct") and v["cap_pct"] > 0.002]
    return round(float(np.median(xs)), 1) if len(xs) >= 20 else None


def team_totals(tab: dict[str, dict], roster_team: dict[str, str] | None = None) -> dict[str, float]:
    """{team: sum of cap hits}; a player's team is his current roster team when given, else the contract row's."""
    out: dict[str, float] = {}
    for pid, v in tab.items():
        t = (roster_team or {}).get(pid) or v.get("team")
        if t and v.get("cap_hit") is not None:
            out[t] = out.get(t, 0.0) + float(v["cap_hit"])
    return {t: round(x, 2) for t, x in out.items()}
