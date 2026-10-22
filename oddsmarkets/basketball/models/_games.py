"""
Builder B's store plumbing: reading `store.json` files straight from the data root (the
contract's path, so the models do not depend on the fetcher), and turning GAME records
into the flat per-game rows the ratings, game model, Elo and backtest share.

    possessions(team_box) = FGA - OREB + TOV + 0.44 * FTA        (TOV = total turnovers, team ones included)
    game possessions      = mean of the two teams' estimates
    pace (per 48 / per 40) = possessions * regulation seconds / played seconds
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from oddsmarkets.basketball.models._io import cache_root, data_root  # noqa: F401  (re-exported)
from oddsmarkets.basketball.models._io import content_digest

COUNTED = ("reg", "cup", "playin", "post")      # stypes that are real competitive games
STANDINGS = ("reg",)                           # stypes that count in the standings ("cup" = the Cup final only)


def store_path(league: str, season: int) -> Path:
    return data_root() / str(league).lower() / str(int(season)) / "store.json"


def load_store(league: str, season: int) -> dict | None:
    p = store_path(league, season)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def seasons_on_disk(league: str) -> list[int]:
    root = data_root() / str(league).lower()
    try:
        return sorted(int(d.name) for d in root.iterdir() if d.name.isdigit() and (d / "store.json").exists())
    except OSError:
        return []


def signature(league: str, seasons: Iterable[int]) -> list:
    """[[season, size, content digest]] of the season stores: path- and mtime-independent, so a cache written on the
    PC still matches on a CI runner (fresh checkout, restored caches)."""
    out = []
    for s in seasons:
        p = store_path(league, s)
        d = content_digest(p)
        out.append([int(s), p.stat().st_size, d] if d is not None else [int(s), None, None])
    return out


def day(d: Any) -> date | None:
    """A date from an ISO string / date / datetime (UTC date of the tip time)."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d)[:10])
    except ValueError:
        return None


def local_day(g: dict) -> date | None:
    """The game's calendar day in US time (tip-off UTC minus 6 h), so a 7:30pm ET game is not 'tomorrow'."""
    s = str(g.get("date") or "")
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
        from datetime import timedelta
        return (t - timedelta(hours=6)).date()
    except ValueError:
        return day(s)


def team_poss(tb: dict | None, players: list | None = None) -> float | None:
    t = tb or {}
    if t.get("fga") is None:
        if not players:
            return None
        fga = sum((r[5] or 0) for r in players)
        oreb = sum((r[10] or 0) for r in players)
        fta = sum((r[9] or 0) for r in players)
        tov = sum((r[15] or 0) for r in players)
    else:
        fga, oreb, fta = t.get("fga") or 0, t.get("oreb") or 0, t.get("fta") or 0
        tov = t.get("tov") or 0                                   # ESPN totalTurnovers (team turnovers included)
    return float(fga - oreb + tov + 0.44 * fta)


def game_seconds(g: dict, league: str) -> float:
    per = 600 if str(league).lower() == "wnba" else 720
    n = int(g.get("periods") or 4)
    return 4 * per + max(0, n - 4) * 300


def game_row(g: dict, league: str) -> dict | None:
    """Flat finished-game row, or None if the game has no final score."""
    if not g or g.get("status") != "post" or g.get("hs") is None or g.get("as") is None:
        return None
    h, a = str(g.get("home")), str(g.get("away"))
    box = g.get("box") or {}
    ph = team_poss((box.get(h) or {}).get("team"), (box.get(h) or {}).get("players"))
    pa = team_poss((box.get(a) or {}).get("team"), (box.get(a) or {}).get("players"))
    ps = [p for p in (ph, pa) if p and p > 20]
    poss = sum(ps) / len(ps) if ps else None
    secs = game_seconds(g, league)
    reg = 4 * (600 if str(league).lower() == "wnba" else 720)
    odds = g.get("odds") or {}
    return {"id": str(g.get("id")), "date": str(g.get("date") or ""), "day": local_day(g), "stype": g.get("stype") or "reg",
            "home": h, "away": a, "neutral": bool(g.get("neutral")), "hs": int(g["hs"]), "as": int(g["as"]),
            "margin": int(g["hs"]) - int(g["as"]), "poss": poss, "pace": (poss * reg / secs) if poss else None,
            "periods": int(g.get("periods") or 4), "spread_home": odds.get("spread_home"), "total": odds.get("total"),
            "venue": g.get("venue") or None}


def finished(games: dict | Iterable[dict], league: str, stypes: Iterable[str] = COUNTED,
             before: Any = None, through: Any = None) -> list[dict]:
    """Finished-game rows sorted by date; `before` excludes that day, `through` includes it."""
    gl = games.values() if isinstance(games, dict) else games
    st = set(stypes)
    b, t = day(before), day(through)
    rows = []
    for g in gl:
        if (g or {}).get("stype", "reg") not in st:
            continue
        r = game_row(g, league)
        if r is None or r["day"] is None:
            continue
        if b and r["day"] >= b:
            continue
        if t and r["day"] > t:
            continue
        rows.append(r)
    rows.sort(key=lambda r: (r["date"], r["id"]))
    return rows


def all_games(league: str, seasons: Iterable[int]) -> dict[int, dict]:
    """{season: store} for the seasons on disk among `seasons`."""
    out = {}
    for s in seasons:
        st = load_store(league, s)
        if st:
            out[int(s)] = st
    return out


def env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).lower() in ("1", "true", "yes")
