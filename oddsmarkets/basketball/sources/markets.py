"""
NBA / WNBA prices from Kalshi and Polymarket (and the DraftKings line ESPN carries), mapped to
ESPN team and player ids.

What exists (surveyed 2026-10-01; Kalshi /series?category=Sports, Polymarket tags "nba" / "wnba")

    Kalshi (series -> one event per season, event ticker suffix = season's two-digit year)
        KXNBA-27        champion, 30 markets, ticker suffix = team code (KXNBA-27-BOS)      -> futures["champion"]
        KXNBAEAST-27 / KXNBAWEST-27  conference champion                                       -> futures["conference"]
        KXNBAMVP-27 (53), KXNBAROY-27, KXNBADPOY-27, KXNBASIXTH-27, KXNBACLUTCH-27  awards     -> futures[award]
        KXNBACUP        NBA Cup champion                                                       -> futures["cup"]
        KXNBAPLAYOFF / KXNBAPLAYIN  per-team qualifiers (binary, not a field)                  -> futures["playoffs"/"playin"]
        KXNBAWINS-27<TEAM>  one event per team, markets "N+ wins" (floor_strike N)             -> futures["win_totals"]
        KXNBAGAME-26OCT03MIATOR  per game, two markets with team-code suffixes                 -> game_prices
        KXWNBA-26 champion (15 markets), KXWNBAGAME per game, KXWNBAWINS win totals
        also, not used: division winners (KXNBAPACIFIC ...), KXNBAEAST1SEED, series, props.
    Polymarket (tag "nba" / "wnba"; slugs carry timestamps, so events are found by title)
        "NBA: 2027 Champion" (~$23M), "NBA: 2027 Eastern/Western Conference Champion",
        "NBA: 2026-27 Rookie of the Year", "NBA: 2026 NBA Cup Winner", "NBA: Team to Make Playoffs",
        "NBA: Team to Make Play-In", per game "nba-<away>-<home>-YYYY-MM-DD" (moneyline market
        sportsMarketType "moneyline", outcomes [team A, team B]); "WNBA: 2026 Champion",
        "WNBA: 2026 Defensive Player of the Year", "wnba-<a>-<b>-YYYY-MM-DD".

Prices and the thin-market rule are F1's (f1/sources/markets.py): a price is the midpoint of a
live two-sided quote ((bid + ask) / 2, 0 < bid <= ask < 1, ask - bid <= 0.12); sources are
averaged per runner; a field market is published only when at least max(4, half the field) runners
are accounted for (quoted, written off by a "no bid / ask <= 2c" quote, or settled No) and the
implied total is within 0.8-1.3, then de-vigged multiplicatively. For award markets the field is
the runners the markets list (not every player in the league).

Names: teams by the Kalshi ticker's team code (alias table to ESPN abbreviations), else
`best_match` over "Location Name", nickname and location; players by `best_match` over the
store's player names (then family names when unique). Unmatched labels are reported.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from oddsmarkets.common import prediction_markets as cpm
from oddsmarkets.common.markets import devig

logger = logging.getLogger(__name__)

FLOOR_ASK = 0.02
MIN_TOTAL, MAX_TOTAL = 0.8, 1.3
POLY_TAG = {"nba": "nba", "wnba": "wnba"}

# Kalshi / Polymarket team codes -> ESPN abbreviations
CODE_ALIASES = {
    "nba": {"GSW": "GS", "NYK": "NY", "SAS": "SA", "NOP": "NO", "NOR": "NO", "UTA": "UTAH", "WAS": "WSH", "PHO": "PHX",
            "BRK": "BKN", "CHO": "CHA", "LAK": "LAL"},
    "wnba": {"CONN": "CON", "GSV": "GS", "LVA": "LV", "LAS": "LV", "LAX": "LA", "NYL": "NY", "WAS": "WSH",
             "PHO": "PHX", "ATLD": "ATL", "TORT": "TOR", "PORF": "POR", "DALW": "DAL"},
}
TITLE_KINDS = {
    "nba": {
        "champion": ("KXNBA", r"^NBA: \d{4} Champion$"),
        "east": ("KXNBAEAST", r"Eastern Conference Champion"),
        "west": ("KXNBAWEST", r"Western Conference Champion"),
        "cup": ("KXNBACUP", r"NBA Cup Winner"),
        "mvp": ("KXNBAMVP", r"\bMVP\b|Most Valuable Player"),
        "roy": ("KXNBAROY", r"Rookie of the Year"),
        "dpoy": ("KXNBADPOY", r"Defensive Player of the Year"),
        "sixth": ("KXNBASIXTH", r"Sixth Man"),
        "clutch": ("KXNBACLUTCH", r"Clutch Player"),
    },
    "wnba": {
        "champion": ("KXWNBA", r"^WNBA: \d{4} Champion$"),
        "mvp": ("KXWNBAMVP", r"\bMVP\b|Most Valuable Player"),
        "roy": ("KXWNBAROY", r"Rookie of the Year"),
        "dpoy": ("KXWNBADPOY", r"Defensive Player of the Year"),
        "sixth": ("KXWNBA6POY", r"Sixth Player"),
    },
}
PLAYER_KINDS = {"mvp", "roy", "dpoy", "sixth", "clutch"}
BINARY_KINDS = {"nba": {"playoffs": ("KXNBAPLAYOFF", r"Team to Make Playoffs"), "playin": ("KXNBAPLAYIN", r"Team to Make Play-In")},
                "wnba": {}}
WINS_SERIES = {"nba": "KXNBAWINS", "wnba": "KXWNBAWINS"}
GAME_SERIES = {"nba": "KXNBAGAME", "wnba": "KXWNBAGAME"}

# indirection so tests can swap the network for canned payloads
kalshi_events = cpm.kalshi_events
polymarket_tag_events = cpm.polymarket_tag_events


def _league(league):
    return "wnba" if str(league or "").lower() == "wnba" else "nba"


def _load_store(league: str, season: int) -> dict:
    try:
        from oddsmarkets.basketball import store as bst
        return bst.load(league, season)
    except Exception:  # noqa: BLE001
        return {}


def season_for(league: str, d: date | None = None) -> int:
    d = d or datetime.now(timezone.utc).date()
    if _league(league) == "wnba":
        return d.year
    return d.year + 1 if d.month >= 8 else d.year


# ── names ────────────────────────────────────────────────────────────────────

def _team_names(info: dict) -> list[str]:
    name, loc = str(info.get("name") or ""), str(info.get("location") or "")
    short = str(info.get("short") or "")
    full = name if (loc and name.lower().startswith(loc.lower())) else f"{loc} {name}".strip()
    nick = short or (name[len(loc):].strip() if loc and name.lower().startswith(loc.lower()) else name)
    out = []
    for x in (full, nick, loc):
        if x and x not in out:
            out.append(x)
    return out


def _nick(info: dict) -> str:
    """'Celtics' from {"name": "Boston Celtics", "location": "Boston"} (or the explicit short name)."""
    name, loc = str(info.get("name") or ""), str(info.get("location") or "")
    if info.get("short"):
        return str(info["short"])
    if loc and name.lower().startswith(loc.lower()):
        return name[len(loc):].strip()
    return name.split()[-1] if name else ""


def map_team(label: str | None, teams: dict[str, dict], code: str | None = None, league: str = "nba") -> str | None:
    """ESPN team id for a market's team code / label, or None when unsure."""
    if not teams:
        return None
    if code:
        c = str(code).upper()
        c = CODE_ALIASES[_league(league)].get(c, c)
        hit = [t for t, v in teams.items() if str((v or {}).get("abbr") or "").upper() == c]
        if len(hit) == 1:
            return hit[0]
    if not label:
        return None
    lab = str(label).strip()
    # "Los Angeles C" / "Los Angeles L": location plus the nickname's initial
    m = re.fullmatch(r"(.+?)\s+([A-Z])", lab)
    if m:
        hit = [t for t, v in teams.items() if cpm.fold(v.get("location") or "") == cpm.fold(m.group(1))
               and _nick(v)[:1].upper() == m.group(2)]
        if len(hit) == 1:
            return hit[0]
        hit = [t for t, v in teams.items() if cpm.fold(m.group(1)) in cpm.fold(v.get("name") or "")
               and cpm.fold(v.get("short") or (v.get("name") or "").split()[-1])[:1] == m.group(2).lower()]
        if len(hit) == 1:
            return hit[0]
    exact = [t for t, v in teams.items() if cpm.fold(lab) in {cpm.fold(x) for x in _team_names(v)}]
    if len(exact) == 1:
        return exact[0]
    # "Los Angeles Clippers" against ESPN's "LA Clippers": a unique nickname ending the label decides
    fl = " " + cpm.fold(lab)
    nick = [t for t, v in teams.items()
            if (n := cpm.fold(_nick(v))) and fl.endswith(" " + n)]
    if len(nick) == 1:
        return nick[0]
    cand = {}
    for t, v in teams.items():
        for x in _team_names(v):
            cand.setdefault(x, set()).add(t)
    cand = {k: next(iter(v)) for k, v in cand.items() if len(v) == 1}
    best = cpm.best_match(lab, list(cand))
    return cand[best] if best else None


def map_player(label: str | None, players: dict[str, dict]) -> str | None:
    """ESPN player id for a market's player label, or None when unsure."""
    if not label or not players:
        return None
    names = {}
    for pid, v in players.items():
        n = str((v or {}).get("name") or "").strip()
        if n:
            names.setdefault(n, []).append(pid)
    names = {k: v[0] for k, v in names.items() if len(v) == 1}
    key = cpm.fold(label)
    exact = [pid for n, pid in names.items() if cpm.fold(n) == key]
    if len(exact) == 1:
        return exact[0]
    m = cpm.best_match(label, list(names), floor=0.85)
    if m:
        return names[m]
    fam: dict[str, list] = {}
    for n, pid in names.items():
        fam.setdefault(n.split()[-1], []).append(pid)
    last = str(label).split()[-1]
    hit = [v[0] for k, v in fam.items() if len(v) == 1 and cpm.fold(k) == cpm.fold(last)]
    return hit[0] if len(hit) == 1 else None


def _ticker_code(ticker: str | None) -> str | None:
    t = str(ticker or "")
    return t.rsplit("-", 1)[-1] if "-" in t else None


# ── parsing one source ───────────────────────────────────────────────────────

def _empty_source() -> dict:
    return {"mid": {}, "floor": set(), "eliminated": set(), "winner": None, "unmatched": []}


def _no_bid_floor(bid, ask) -> bool:
    b, a = cpm._f(bid), cpm._f(ask)
    return (b is None or b <= 0) and a is not None and 0 < a <= FLOOR_ASK


def parse_kalshi_field(event: dict, mapper) -> dict:
    """mapper(label, code) -> id. Mids / floor / settled runners from a Kalshi field event."""
    out = _empty_source()
    for m in (event or {}).get("markets") or []:
        label = str(m.get("yes_sub_title") or m.get("subtitle") or "")
        rid = mapper(label, _ticker_code(m.get("ticker")))
        if not rid:
            if label:
                out["unmatched"].append(label)
            continue
        result = str(m.get("result") or "").lower()
        if result == "no":
            out["eliminated"].add(rid)
            continue
        if result == "yes":
            out["winner"] = rid
            continue
        p = cpm.kalshi_price(m)
        if p is not None:
            out["mid"][rid] = p
        elif _no_bid_floor(m.get("yes_bid_dollars"), m.get("yes_ask_dollars")):
            out["floor"].add(rid)
    return out


def parse_poly_field(event: dict, mapper) -> dict:
    """Mids / floor / eliminated runners from a Polymarket field event (one yes/no market per runner)."""
    out = _empty_source()
    for m in (event or {}).get("markets") or []:
        label = str(m.get("groupItemTitle") or "")
        if not label or label.lower() in ("other", "another player", "field") or re.fullmatch(r"(team|player) [a-z]", label.lower()):
            continue
        rid = mapper(label, None)
        if not rid:
            out["unmatched"].append(label)
            continue
        settled = cpm.poly_resolved(m)
        if settled == 0.0:
            out["eliminated"].add(rid)
            continue
        if settled == 1.0:
            out["winner"] = rid
            continue
        if m.get("closed"):
            continue
        p = cpm.poly_price(m)
        if p is not None:
            out["mid"][rid] = p
        elif _no_bid_floor(m.get("bestBid"), m.get("bestAsk")):
            out["floor"].add(rid)
    return out


def assemble(sources: dict[str, dict], ids: Iterable[str] | None, kind: str, markets: dict | None = None) -> dict:
    """
    TITLE: {"available","reason","probs","mid","odds","sources","by_source","floor","eliminated","unmatched",
            "field","quoted","accounted","implied_total","overround","markets","kind"}.
    `ids` None = the field is every runner any source lists (award markets).
    """
    pooled: dict[str, list[float]] = {}
    floor, elim, unmatched, winner = set(), set(), [], None
    for src in sources.values():
        for rid, p in src["mid"].items():
            pooled.setdefault(rid, []).append(p)
        floor |= src["floor"]
        elim |= src["eliminated"]
        unmatched += src["unmatched"]
        winner = winner or src.get("winner")
    if ids is None:
        ids = sorted(set(pooled) | floor | elim)
    ids = list(ids)
    mid = {r: sum(ps) / len(ps) for r, ps in pooled.items() if r not in elim}
    floor = (floor - set(mid)) - elim
    total = sum(mid.values())
    accounted = set(mid) | floor | elim
    need = max(4, len(ids) // 2)
    by_source = {k: {r: round(p, 4) for r, p in v["mid"].items()} for k, v in sources.items()}
    base = {"kind": kind, "markets": markets or {}, "field": len(ids), "quoted": len(mid), "accounted": len(accounted),
            "implied_total": round(total, 4), "overround": round(total - 1.0, 4), "unmatched": sorted(set(unmatched)),
            "sources": sorted(sources), "by_source": by_source, "eliminated": sorted(elim), "floor": sorted(floor)}
    if winner:
        return {**base, "available": False, "reason": f"settled: {winner} won", "probs": {}, "mid": {}, "winner": winner}
    if len(accounted) < need or not (MIN_TOTAL <= total <= MAX_TOTAL) or not mid:
        reason = f"thin: {len(accounted)} of {len(ids)} runners accounted for (need {need}), implied total {total:.2f}"
        return {**base, "available": False, "reason": reason, "probs": {}, "mid": {k: round(v, 4) for k, v in mid.items()}}
    fair = devig({r: 1.0 / p for r, p in mid.items()})
    probs = {r: round(fair.get(r, 0.0), 5) for r in ids if r in fair}
    for r in floor | elim:
        probs.setdefault(r, 0.0)
    probs = dict(sorted(probs.items(), key=lambda kv: -kv[1]))
    return {**base, "available": True, "reason": None, "probs": probs, "mid": {k: round(v, 4) for k, v in mid.items()},
            "odds": {r: round(1.0 / p, 4) for r, p in mid.items()}}


# ── event selection ──────────────────────────────────────────────────────────

def _yy(season: int) -> str:
    return f"{int(season) % 100:02d}"


def _kalshi_events_for(series: str, season: int) -> list[dict]:
    """The series' events for a season (ticker suffix -27, or -27EAST / -27WEST for split events)."""
    yy = _yy(season)
    out = []
    for e in kalshi_events(series) or []:
        t = str(e.get("event_ticker") or "")
        if re.search(rf"-{yy}$", t) or re.search(rf"-{yy}[A-Z]+$", t):
            out.append(e)
    return out


def _kalshi_event(series: str, season: int) -> dict | None:
    evs = _kalshi_events_for(series, season)
    return evs[0] if evs else None


def _poly_season_ok(ev: dict, season: int) -> bool:
    title = str(ev.get("title") or "")
    if str(season) in title or f"{season - 1}-{season % 100:02d}" in title:
        return True
    if re.search(r"\b20\d\d\b", title):
        return False
    end = str(ev.get("endDate") or "")[:4]
    return end == str(season)


def _poly_events(league: str) -> list[dict]:
    return polymarket_tag_events(POLY_TAG[_league(league)]) or []


def _poly_find(events: list[dict], pattern: str, season: int, league: str) -> dict | None:
    for ev in events:
        title = str(ev.get("title") or "")
        if ev.get("closed"):
            continue
        if _league(league) == "nba" and title.upper().startswith("WNBA"):
            continue
        if re.search(pattern, title, re.I) and _poly_season_ok(ev, season):
            return ev
    return None


# ── public ───────────────────────────────────────────────────────────────────

def title_prices(league: str, season: int, kind: str = "champion", store: dict | None = None,
                 poly_events: list[dict] | None = None) -> dict:
    """One field market (champion, east, west, cup, mvp, roy, dpoy, sixth, clutch) as a TITLE dict. Never raises."""
    league = _league(league)
    try:
        spec = TITLE_KINDS[league].get(kind)
        if not spec:
            return {"kind": kind, "available": False, "reason": "no such market", "probs": {}}
        s = store if store is not None else _load_store(league, season)
        teams, players = s.get("teams") or {}, s.get("players") or {}
        if kind in PLAYER_KINDS:
            def mapper(label, code):
                return map_player(label, players)
            ids = None
        else:
            def mapper(label, code):
                return map_team(label, teams, code, league)
            ids = list(teams)
            if kind in ("east", "west"):
                ids = [t for t, v in teams.items() if str(v.get("conference") or "").lower().startswith(kind)] or ids
        sources, markets = {}, {}
        label_season = season - 1 if kind == "cup" else season       # the NBA Cup is named for its December final
        ev = _kalshi_event(spec[0], label_season)
        if ev:
            sources["kalshi"] = parse_kalshi_field(ev, mapper)
            markets["kalshi"] = ev.get("event_ticker")
        pev = _poly_find(poly_events if poly_events is not None else _poly_events(league), spec[1], label_season, league)
        if pev:
            sources["polymarket"] = parse_poly_field(pev, mapper)
            markets["polymarket"] = pev.get("slug")
        return assemble(sources, ids, kind, markets)
    except Exception as exc:  # noqa: BLE001
        logger.info("basketball title_prices(%s, %s) failed: %s", league, kind, exc)
        return {"kind": kind, "available": False, "reason": f"error: {exc}", "probs": {}}


def binary_prices(league: str, season: int, kind: str, store: dict | None = None, poly_events: list[dict] | None = None) -> dict:
    """Per-team yes/no markets (playoffs, playin): {"available", "probs": {tid: mean mid}, "by_source", "markets"}."""
    league = _league(league)
    spec = BINARY_KINDS[league].get(kind)
    if not spec:
        return {"kind": kind, "available": False, "reason": "no such market", "probs": {}}
    try:
        s = store if store is not None else _load_store(league, season)
        teams = s.get("teams") or {}

        def mapper(label, code):
            return map_team(label, teams, code, league)
        srcs, markets = {}, {}
        evs = _kalshi_events_for(spec[0], season)
        if evs:
            merged = {"markets": [m for e in evs for m in (e.get("markets") or [])]}
            srcs["kalshi"] = parse_kalshi_field(merged, mapper)
            markets["kalshi"] = ",".join(str(e.get("event_ticker")) for e in evs)
        pev = _poly_find(poly_events if poly_events is not None else _poly_events(league), spec[1], season, league)
        if pev:
            srcs["polymarket"] = parse_poly_field(pev, mapper)
            markets["polymarket"] = pev.get("slug")
        pooled: dict[str, list] = {}
        for v in srcs.values():
            for t, p in v["mid"].items():
                pooled.setdefault(t, []).append(p)
            for t in v["eliminated"]:
                pooled.setdefault(t, []).append(0.0)
        probs = {t: round(sum(v) / len(v), 4) for t, v in pooled.items()}
        return {"kind": kind, "available": bool(probs), "probs": probs, "markets": markets,
                "by_source": {k: {t: round(p, 4) for t, p in v["mid"].items()} for k, v in srcs.items()},
                "unmatched": sorted({u for v in srcs.values() for u in v["unmatched"]})}
    except Exception as exc:  # noqa: BLE001
        return {"kind": kind, "available": False, "reason": f"error: {exc}", "probs": {}}


def parse_win_ladder(event: dict) -> dict | None:
    """{"ladder": {N: P(W >= N)}, "line", "p_over"} from one Kalshi win-total event, or None."""
    lad = {}
    for m in (event or {}).get("markets") or []:
        try:
            n = int(float(m.get("floor_strike")))
        except (TypeError, ValueError):
            mm = re.search(r"(\d+)\+", str(m.get("yes_sub_title") or ""))
            if not mm:
                continue
            n = int(mm.group(1))
        p = cpm.kalshi_price(m)
        if p is not None:
            lad[n] = p
    if not lad:
        return None
    ks = sorted(lad)
    # enforce a non-increasing ladder (isotonic by running minimum from the left)
    run, mono = 1.0, {}
    for k in ks:
        run = min(run, lad[k])
        mono[k] = round(run, 4)
    best = min(ks, key=lambda k: abs(mono[k] - 0.5))
    return {"ladder": mono, "line": best - 0.5, "p_over": mono[best]}


def win_totals(league: str, season: int, store: dict | None = None) -> dict[str, dict]:
    """{tid: {"line","p_over","ladder","ticker"}} from Kalshi's per-team win-total events."""
    league = _league(league)
    out = {}
    try:
        s = store if store is not None else _load_store(league, season)
        teams = s.get("teams") or {}
        yy = _yy(season)
        for ev in kalshi_events(WINS_SERIES[league]) or []:
            t = str(ev.get("event_ticker") or "")
            m = re.search(rf"-{yy}([A-Z]+)$", t)
            if not m:
                continue
            tid = map_team(str(ev.get("sub_title") or "").split("(")[0].strip(), teams, m.group(1), league)
            lad = parse_win_ladder(ev)
            if tid and lad:
                out[tid] = {**lad, "ticker": t}
    except Exception as exc:  # noqa: BLE001
        logger.info("basketball win_totals failed: %s", exc)
    return out


def futures(league: str, season: int | None = None, store: dict | None = None) -> dict:
    """{"champion": TITLE, "conference": {"East": TITLE, "West": TITLE}, "mvp", "roy", "dpoy", "sixth", "clutch",
    "cup": TITLE, "playoffs": {...}, "playin": {...}, "win_totals": {tid: {...}}, "season", "generated_at"}."""
    league = _league(league)
    season = int(season or season_for(league))
    s = store if store is not None else _load_store(league, season)
    pev = _poly_events(league)
    out: dict[str, Any] = {"league": league, "season": season,
                           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    kinds = TITLE_KINDS[league]
    for kind in kinds:
        if kind in ("east", "west"):
            continue
        out[kind] = title_prices(league, season, kind, store=s, poly_events=pev)
    if "east" in kinds:
        out["conference"] = {"East": title_prices(league, season, "east", store=s, poly_events=pev),
                             "West": title_prices(league, season, "west", store=s, poly_events=pev)}
    for kind in BINARY_KINDS[league]:
        out[kind] = binary_prices(league, season, kind, store=s, poly_events=pev)
    out["win_totals"] = win_totals(league, season, store=s)
    return out


# ── per game ─────────────────────────────────────────────────────────────────

_MON = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def kalshi_game_date(ticker: str) -> date | None:
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", str(ticker or ""))
    if not m or m.group(2) not in _MON:
        return None
    try:
        return date(2000 + int(m.group(1)), _MON[m.group(2)], int(m.group(3)))
    except ValueError:
        return None


def _american_to_p(ml) -> float | None:
    try:
        x = float(ml)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x == 0:
        return None
    return 100.0 / (x + 100.0) if x > 0 else -x / (-x + 100.0)


def _store_games_on(s: dict, d: date) -> list[dict]:
    from oddsmarkets.basketball.models._games import local_day
    out = []
    for g in (s.get("games") or {}).values():
        ld = local_day(g)
        if ld and abs((ld - d).days) <= 1:
            out.append(g)
    return out


def _match_game(cands: list[dict], a: str | None, b: str | None, d: date | None) -> dict | None:
    if not a or not b:
        return None
    from oddsmarkets.basketball.models._games import local_day
    hit = [g for g in cands if {str(g.get("home")), str(g.get("away"))} == {a, b}]
    if d:
        exact = [g for g in hit if local_day(g) == d]
        hit = exact or hit
    return hit[0] if len(hit) == 1 else (hit[0] if hit else None)


def game_prices(league: str, d: Any = None, store: dict | None = None, poly_events: list[dict] | None = None) -> dict[str, dict]:
    """
    {game_id: {"p_home", "sources": [{"source","p_home","market"}], "spread_home", "total", "home", "away"}}
    for the store's games on day `d` (US date, +-1 day tolerance). p_home is the mean of the prediction-market
    sources (two-sided mids, de-vigged across the two sides); without them, the DraftKings moneyline
    (de-vigged), else the DraftKings spread through game.spread_to_p. Never raises.
    """
    league = _league(league)
    try:
        d = d if isinstance(d, date) else (date.fromisoformat(str(d)[:10]) if d else datetime.now(timezone.utc).date())
        season = season_for(league, d)
        s = store if store is not None else _load_store(league, season)
        teams = s.get("teams") or {}
        cands = _store_games_on(s, d)
        out: dict[str, dict] = {}

        def rec(g):
            gid = str(g["id"])
            if gid not in out:
                odds = g.get("odds") or {}
                out[gid] = {"home": str(g["home"]), "away": str(g["away"]), "sources": [],
                            "spread_home": odds.get("spread_home"), "total": odds.get("total"), "p_home": None}
            return out[gid]

        for ev in kalshi_events(GAME_SERIES[league]) or []:
            ed = kalshi_game_date(ev.get("event_ticker"))
            if ed and abs((ed - d).days) > 1:
                continue
            q = {}
            for m in ev.get("markets") or []:
                tid = map_team(m.get("yes_sub_title"), teams, _ticker_code(m.get("ticker")), league)
                p = cpm.kalshi_price(m)
                if tid and p is not None:
                    q[tid] = p
            ids = [map_team(m.get("yes_sub_title"), teams, _ticker_code(m.get("ticker")), league) for m in ev.get("markets") or []]
            ids = [i for i in ids if i]
            g = _match_game(cands, *(ids + [None, None])[:2], ed)
            if not g or not q:
                continue
            h, a = str(g["home"]), str(g["away"])
            if h in q and a in q:
                ph = q[h] / (q[h] + q[a])
            elif h in q:
                ph = q[h]
            else:
                ph = 1.0 - q[a]
            rec(g)["sources"].append({"source": "kalshi", "p_home": round(ph, 4), "market": ev.get("event_ticker")})
        pevs = poly_events if poly_events is not None else _poly_events(league)
        for ev in pevs:
            slug = str(ev.get("slug") or "")
            mm = re.fullmatch(rf"{league}-([a-z]+)-([a-z]+)-(\d{{4}}-\d{{2}}-\d{{2}})", slug)
            if not mm or ev.get("closed"):
                continue
            ed = date.fromisoformat(mm.group(3))
            if abs((ed - d).days) > 1:
                continue
            ml = next((m for m in ev.get("markets") or [] if m.get("sportsMarketType") == "moneyline"), None)
            if not ml:
                continue
            outs = ml.get("outcomes")
            if isinstance(outs, str):
                try:
                    outs = json.loads(outs)
                except ValueError:
                    outs = None
            if not outs or len(outs) != 2:
                continue
            ta, tb = map_team(outs[0], teams, None, league), map_team(outs[1], teams, None, league)
            g = _match_game(cands, ta, tb, ed)
            p = cpm.poly_price(ml)
            if not g or p is None:
                continue
            ph = p if str(g["home"]) == ta else 1.0 - p
            rec(g)["sources"].append({"source": "polymarket", "p_home": round(ph, 4), "market": slug})
        for g in cands:
            odds = g.get("odds") or {}
            ph_ml = _american_to_p(odds.get("ml_home"))
            pa_ml = _american_to_p(odds.get("ml_away"))
            if ph_ml and pa_ml:
                rec(g)["sources"].append({"source": "draftkings_ml", "p_home": round(ph_ml / (ph_ml + pa_ml), 4),
                                          "market": odds.get("provider")})
            if odds.get("spread_home") is not None:
                from oddsmarkets.basketball.models.game import spread_to_p
                p = spread_to_p(odds.get("spread_home"), league)
                if p is not None:
                    rec(g)["sources"].append({"source": "draftkings_spread", "p_home": round(p, 4), "market": odds.get("provider")})
        for gid, r in out.items():
            pm = [x["p_home"] for x in r["sources"] if x["source"] in ("kalshi", "polymarket")]
            ml = [x["p_home"] for x in r["sources"] if x["source"] == "draftkings_ml"]
            spd = [x["p_home"] for x in r["sources"] if x["source"] == "draftkings_spread"]
            pick = pm or ml or spd
            r["p_home"] = round(sum(pick) / len(pick), 4) if pick else None
            r["basis"] = "prediction_markets" if pm else ("draftkings_ml" if ml else ("draftkings_spread" if spd else None))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("basketball game_prices failed: %s", exc)
        return {}
