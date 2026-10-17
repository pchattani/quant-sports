"""
NHL stats REST (https://api.nhle.com/stats/rest/en): shift charts, season reports and the season list.

Endpoints (verified 1 Oct 2026):
  shiftcharts?cayenneExp=gameId=X          {"data": [...], "total"}: one row per shift (typeCode 517: playerId, teamId,
                                           teamAbbrev, period, startTime / endTime "mm:ss" in the period, duration,
                                           shiftNumber) plus goal markers (typeCode 505, detailCode 8xx, shiftNumber 0).
                                           2010-11 -> (2009-10 games answer total 0).
  skater/summary, skater/realtime, goalie/summary, team/summary, team/realtime
      ?limit=-1&cayenneExp=seasonId=S and gameTypeId=T     one row per player (team) per season
  season                                   every season: startDate, regularSeasonEndDate, endDate, numberOfGames,
                                           totalRegularSeasonGames, rules in use (ties, ROW, wild card, ...)
  team                                     every NHL team id with tri-code and franchise id

Fallback for games whose shift charts answer empty (e.g. 57 games of 2024-25, 2024021235 .. 2024021291, empty on
1 Oct 2026): the NHL's HTML time-on-ice reports, https://www.nhl.com/scores/htmlreports/<S>/T{H|V}<gameId[4:]>.HTM
(TH = home, TV = visitors): one block per player ("4 BYRAM, BOWEN") with rows Shift #, Per, Start (elapsed / game),
End (elapsed / game), Duration. `shifts_from_toi_html` maps players by team and sweater number through the
play-by-play roster spots and returns a shiftcharts-shaped answer ({"data", "total", "source": "html"}).
"""
from __future__ import annotations

import html as _html
import logging
import re
from typing import Any

from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

REST = "https://api.nhle.com/stats/rest/en"
INTERVAL = 0.25
REPORTS = {"skater_summary": "skater/summary", "skater_realtime": "skater/realtime", "goalie_summary": "goalie/summary",
           "team_summary": "team/summary", "team_realtime": "team/realtime"}


def shiftcharts(c: Client, game_id: int | str) -> dict | None:
    return c.get(f"{REST}/shiftcharts", {"cayenneExp": f"gameId={game_id}"})


def report(c: Client, name: str, season: int, game_type: int = 2) -> list[dict] | None:
    path = REPORTS.get(name, name)
    params = {"limit": -1, "cayenneExp": f"seasonId={int(season)} and gameTypeId={int(game_type)}"}
    if path.startswith("skater") or path.startswith("goalie"):
        params["sort"] = "playerId"
    d = c.get(f"{REST}/{path}", params)
    return None if d is None else list(d.get("data") or [])


def seasons(c: Client) -> dict[int, dict]:
    d = c.get(f"{REST}/season")
    out = {}
    for s in (d or {}).get("data") or []:
        out[int(s["id"])] = {"start": str(s.get("startDate") or "")[:10],
                             "regular_end": str(s.get("regularSeasonEndDate") or "")[:10],
                             "end": str(s.get("endDate") or "")[:10], "games": s.get("numberOfGames"),
                             "total_regular": s.get("totalRegularSeasonGames"),
                             "preseason_start": str(s.get("preseasonStartdate") or "")[:10] or None}
    return out


def _mmss(s: Any) -> int | None:
    try:
        m, sec = str(s).split(":")
        return int(m) * 60 + int(sec)
    except (ValueError, AttributeError):
        return None


def compact_shifts(raw: dict | None) -> list[dict]:
    """Shift rows (typeCode 517) as {pid, team_id, team, period, start, end} with start / end in seconds of the
    period. A shift without an end time takes start + duration; rows without a usable start are dropped."""
    out = []
    for r in (raw or {}).get("data") or []:
        if r.get("typeCode") not in (517, None) or r.get("detailCode") not in (0, None):
            continue
        st = _mmss(r.get("startTime"))
        en = _mmss(r.get("endTime"))
        if en is None:
            dur = _mmss(r.get("duration"))
            en = st + dur if st is not None and dur is not None else None
        if st is None or en is None or r.get("playerId") is None or r.get("period") is None:
            continue
        out.append({"pid": int(r["playerId"]), "team_id": r.get("teamId"), "team": r.get("teamAbbrev"),
                    "period": int(r["period"]), "start": st, "end": en})
    return out


# ── HTML time-on-ice reports (fallback) ─────────────────────────────────────

HTML = "https://www.nhl.com/scores/htmlreports"
_PLAYER = re.compile(r'class="playerHeading[^"]*"[^>]*>\s*(\d+)\s+([^<]*)</td>', re.I)
_ROW = re.compile(r"<tr[^>]*class=\"\s*(?:odd|even)Color\"[^>]*>(.*?)</tr>", re.I | re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)


def toi_report(c: Client, season: int, game_id: int | str, side: str) -> str | None:
    """side 'H' (home) or 'V' (visitors)."""
    return c.get_text(f"{HTML}/{int(season)}/T{side}{str(game_id)[4:]}.HTM")


def parse_toi_html(text: str | None) -> list[dict]:
    """[{number, name, period, start, end}] (seconds elapsed in the period) from a TOI report."""
    if not text:
        return []
    out = []
    heads = list(_PLAYER.finditer(text))
    for k, m in enumerate(heads):
        block = text[m.end(): heads[k + 1].start() if k + 1 < len(heads) else len(text)]
        num, name = int(m.group(1)), _html.unescape(m.group(2)).strip()
        for row in _ROW.finditer(block):
            cells = [re.sub(r"<[^>]+>", "", _html.unescape(x)).strip() for x in _CELL.findall(row.group(1))]
            if len(cells) < 5 or not cells[0].isdigit():
                continue
            per = {"OT": 4, "SO": 5}.get(cells[1].upper(), None)
            per = per or (int(cells[1]) if cells[1].isdigit() else None)
            st, en = _mmss(cells[2].split("/")[0].strip()), _mmss(cells[3].split("/")[0].strip())
            if per is None or st is None or en is None:
                continue
            out.append({"number": num, "name": name, "period": per, "start": st, "end": en})
    return out


def _fmt(sec: int) -> str:
    return f"{sec // 60:02d}:{sec % 60:02d}"


def shifts_from_toi_html(home_html: str | None, away_html: str | None, pbp_raw: dict) -> dict | None:
    """A shiftcharts-shaped answer built from the two TOI reports, or None when either side does not parse."""
    home_id, away_id = pbp_raw["homeTeam"]["id"], pbp_raw["awayTeam"]["id"]
    by_num = {(p.get("teamId"), p.get("sweaterNumber")): p["playerId"] for p in pbp_raw.get("rosterSpots") or []}
    data, unmatched = [], 0
    for tid, text in ((home_id, home_html), (away_id, away_html)):
        rows = parse_toi_html(text)
        if not rows:
            return None
        for r in rows:
            pid = by_num.get((tid, r["number"]))
            if pid is None:
                unmatched += 1
                continue
            data.append({"playerId": pid, "teamId": tid, "period": r["period"], "startTime": _fmt(r["start"]),
                         "endTime": _fmt(r["end"]), "duration": _fmt(max(0, r["end"] - r["start"])), "typeCode": 517,
                         "detailCode": 0, "gameId": pbp_raw.get("id")})
    return {"data": data, "total": len(data), "source": "html", "unmatched": unmatched}
