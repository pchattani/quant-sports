"""
NFL prices from Kalshi and Polymarket, mapped to nflverse team abbreviations and player names.

What exists (surveyed 2026-10-01; fixture tests/nfl/fixtures/markets_c.json)

    Kalshi (/events?series_ticker=..., with nested markets)
        KXSB-27                    Super Bowl ("2027 Pro Football Champion"), one market per team, ticker suffix = code
        KXNFLAFCCHAMP-27 / KXNFLNFCCHAMP-27     conference champions
        KXNFLAFCEAST-27 ... KXNFLNFCWEST-27      division winners (labels "Buffalo", "Los Angeles R", "New York G")
        KXNFL1SEED-AFC26 / -NFC26  #1 seed (note: the season's own two digits, not the following year's)
        KXNFLPLAYOFF-27            make the playoffs, per-team yes/no
        KXNFLWINS-27ARI            win totals, "N+ wins" ladder (floor_strike N), one event per team
        KXNFLMVP-27, KXNFLOPOTY-27, KXNFLDPOTY-27, KXNFLOROTY-27, (KXNFLDROTY, KXNFLCPOTY, KXNFLCOTY: no open
                                   event on 2026-10-01; parsed the same way when they list)
        KXNFLGAME-26OCT01PITCLE    game winner (away code then home code), one market per team
        KXNFLSPREAD-26OCT01PITCLE  "<TEAM> wins by over X points" (ticker suffix code + ceil(X), floor_strike X)
        KXNFLTOTAL-26OCT01PITCLE   "Over X points" ladder
        KXNFLTEAMTOTAL-26OCT01PITCLE  "<TEAM> over X points" per team (ticker suffix code + ceil(X))
        Kalshi codes are nflverse's except JAC (JAX) and LAR (LA).
    Polymarket
        tag "nfl": "Pro Football: 2027 Champion", "... 2027 AFC Champion" / "NFC Champion", "Pro Football: 2026 MVP
        Winner", "Pro Football: 2026-27 AP Offensive Player of the Year Winner" (DPOY, OROY, DROY, Comeback, Coach of
        the Year likewise), "Pro Football: AFC East Champion" (no year in the title), "Pro Football: Team to Make
        Postseason", "Pro Football: 2026-27 AFC #1 Seed", "Pro Football: Bills 2026 Win Total" ("N.5+ Wins" ladder),
        "Pro Football: Team to advance to AFC Championship Game" / "AFC Team to advance to Divisional Round".
        The tag lists many player props first; `poly_events()` pages through it and keeps the futures, and fetches
        the fixed division / postseason slugs directly when the pages miss them.
        Games: /events?series_id=12185, slug "nfl-<away>-<home>-YYYY-MM-DD" (UTC date of kickoff), markets
        moneyline (outcomes away, home nicknames), spreads ("Spread: Steelers (-1.5)", price = first outcome covers
        `line`), totals (`line`, outcomes Over / Under).

Prices and the thin-market rule are Hardwood's (basketball/sources/markets.py): a price is the midpoint of a live
two-sided quote ((bid + ask) / 2, 0 < bid <= ask < 1, ask - bid <= 0.12); team field markets are pooled across
sources, published only when at least max(4, half the field) runners are accounted for and the implied total is
within 0.8-1.3, then de-vigged multiplicatively. Award fields (open-ended, 40-80 runners) are de-vigged per source
(`assemble_field`: implied total 0.8-1.3, or up to 1.6 when 20+ runners are quoted) and averaged across sources.
Two-way markets (games) are de-vigged across their two sides.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from oddsmarkets.basketball.sources.markets import (  # noqa: F401  (sport-neutral parsers)
    _no_bid_floor,
    assemble,
    kalshi_game_date,
    parse_kalshi_field,
    parse_poly_field,
    parse_win_ladder,
)
from oddsmarkets.common import prediction_markets as cpm
from oddsmarkets.common.edge import devig as _dv

logger = logging.getLogger(__name__)

POLY_TAG = "nfl"
POLY_GAMES_SERIES = 12185
CODE_ALIASES = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS", "STL": "LA", "SD": "LAC", "OAK": "LV", "ARZ": "ARI",
                "GNB": "GB", "KAN": "KC", "NWE": "NE", "NOR": "NO", "SFO": "SF", "TAM": "TB", "SDG": "LAC", "HST": "HOU",
                "BLT": "BAL", "CLV": "CLE", "LVR": "LV"}
DIVISIONS = ("AFC East", "AFC North", "AFC South", "AFC West", "NFC East", "NFC North", "NFC South", "NFC West")
TITLE_KINDS = {
    "champion": ("KXSB", r"Pro Football: 20\d\d Champion|Super Bowl Champion"),
    "AFC": ("KXNFLAFCCHAMP", r"\bAFC Champion\b(?!ship)"),
    "NFC": ("KXNFLNFCCHAMP", r"\bNFC Champion\b(?!ship)"),
}
AWARD_KINDS = {
    "mvp": ("KXNFLMVP", r"\bMVP\b"),
    "opoy": ("KXNFLOPOTY", r"Offensive Player of the Year"),
    "dpoy": ("KXNFLDPOTY", r"Defensive Player of the Year"),
    "oroy": ("KXNFLOROTY", r"Offensive Rookie of the Year"),
    "droy": ("KXNFLDROTY", r"Defensive Rookie of the Year"),
    "cpoy": ("KXNFLCPOTY", r"Comeback Player of the Year"),
    "coty": ("KXNFLCOTY", r"Coach of the Year"),
}
POLY_SLUGS = ["pro-football-afc-east-champion", "pro-football-afc-north-champion", "pro-football-afc-south-champion",
              "pro-football-afc-west-champion", "pro-football-nfc-east-champion", "pro-football-nfc-north-champion",
              "pro-football-nfc-south-champion", "pro-football-nfc-west-champion", "nfl-team-to-make-postseason"]
FUTURE_WORDS = ("champion", "mvp", "player of the year", "rookie of the year", "coach of the year", "postseason",
                "#1 seed", "win total", "advance to")

# indirection so tests can swap the network for canned payloads
kalshi_events = cpm.kalshi_events
polymarket_tag_events = cpm.polymarket_tag_events
polymarket_event = cpm.polymarket_event


def season_for(d: date | None = None) -> int:
    d = d or datetime.now(timezone.utc).date()
    return d.year if d.month >= 3 else d.year - 1


# ── teams ────────────────────────────────────────────────────────────────────

def teams_info(season: int, store: dict | None = None) -> dict[str, dict]:
    """{abbr: {"name", "nick", "loc", "conf", "div"}} from canon (falling back to the store's teams)."""
    out = {}
    try:
        from oddsmarkets.nfl import canon
        for t, v in canon.teams(season).items():
            out[t] = {"name": v.get("name") or t, "conf": v.get("conf"), "div": v.get("div")}
    except Exception:  # noqa: BLE001
        for t, v in ((store or {}).get("teams") or {}).items():
            out[t] = {"name": (v or {}).get("name") or t, "conf": (v or {}).get("conference"), "div": (v or {}).get("division")}
    for t, v in out.items():
        name = str(v["name"])
        nick = "Football Team" if name.endswith("Football Team") else name.split()[-1]
        v["nick"] = nick
        v["loc"] = name[: -len(nick)].strip() if name.endswith(nick) else name
    return out


def map_team(label: str | None, teams: dict[str, dict], code: str | None = None) -> str | None:
    """nflverse abbreviation for a market's team code / label ("Los Angeles R", "New York G", "Steelers"), or None."""
    if not teams:
        return None
    if code:
        c = str(code).upper()
        c = CODE_ALIASES.get(c, c)
        if c in teams:
            return c
    if not label:
        return None
    lab = str(label).strip()
    fl = cpm.fold(lab)
    m = re.fullmatch(r"(.+?)\s+([A-Za-z])", lab)
    if m:
        loc, ini = cpm.fold(m.group(1)), m.group(2).lower()
        hit = [t for t, v in teams.items() if cpm.fold(v["loc"]) == loc and cpm.fold(v["nick"]).startswith(ini)]
        if len(hit) == 1:
            return hit[0]
    m = re.fullmatch(r"([A-Z]{2,3})\s+(.+)", lab)                      # "PIT Steelers"
    if m:
        c = CODE_ALIASES.get(m.group(1), m.group(1))
        if c in teams:
            return c
    keys: dict[str, set] = {}
    for t, v in teams.items():
        for x in (v["name"], v["nick"], v["loc"], t):
            keys.setdefault(cpm.fold(str(x)), set()).add(t)
    if fl in keys and len(keys[fl]) == 1:
        return next(iter(keys[fl]))
    nick = [t for t, v in teams.items() if (n := cpm.fold(v["nick"])) and (" " + fl).endswith(" " + n)]
    if len(nick) == 1:
        return nick[0]
    cand = {k: next(iter(v)) for k, v in keys.items() if len(v) == 1}
    best = cpm.best_match(lab, list(cand))
    return cand[best] if best else None


def _ticker_code(ticker: str | None) -> str | None:
    t = str(ticker or "")
    return t.rsplit("-", 1)[-1] if "-" in t else None


# ── event selection ──────────────────────────────────────────────────────────

def _yys(season: int) -> tuple[str, str]:
    return f"{(season + 1) % 100:02d}", f"{season % 100:02d}"


def _kalshi_series(series: str, kalshi: dict | None) -> list[dict]:
    if kalshi is not None:
        return list(kalshi.get(series) or [])
    return kalshi_events(series) or []


def _kalshi_event(series: str, season: int, kalshi: dict | None) -> dict | None:
    nxt, cur = _yys(season)
    evs = _kalshi_series(series, kalshi)
    for yy in (nxt, cur):
        for e in evs:
            if re.search(rf"-{yy}$", str(e.get("event_ticker") or "")):
                return e
    return None


def poly_events(pages: int = 8, closed: bool = False) -> list[dict]:
    """Polymarket futures under tag "nfl" (paged; player props dropped) plus the fixed-slug events."""
    out, seen = [], set()
    for k in range(pages):
        rows = cpm._get(f"{cpm.GAMMA}/events", {"tag_slug": POLY_TAG, "closed": "true" if closed else "false",
                                               "limit": 100, "offset": 100 * k}) or []
        if not isinstance(rows, list) or not rows:
            break
        for e in rows:
            t = str(e.get("title") or "").lower()
            if any(w in t for w in FUTURE_WORDS) and e.get("slug") not in seen:
                seen.add(e.get("slug"))
                out.append(e)
    for s in POLY_SLUGS:
        if s not in seen:
            e = polymarket_event(s)
            if e:
                out.append(e)
                seen.add(s)
    return out


def poly_games(closed: bool = False) -> list[dict]:
    rows = cpm._get(f"{cpm.GAMMA}/events", {"series_id": POLY_GAMES_SERIES, "closed": "true" if closed else "false",
                                           "limit": 200})
    return rows if isinstance(rows, list) else []


def _poly_season_ok(ev: dict, season: int) -> bool:
    title = str(ev.get("title") or "")
    if f"{season}-{(season + 1) % 100:02d}" in title or str(season + 1) in title or str(season) in title:
        return True
    if re.search(r"\b20\d\d\b", title):
        return False
    end = str(ev.get("endDate") or "")[:4]
    return end in (str(season), str(season + 1))


def _poly_find(events: list[dict], pattern: str, season: int, exclude: str | None = None) -> dict | None:
    for ev in events or []:
        title = str(ev.get("title") or "")
        if ev.get("closed"):
            continue
        if exclude and re.search(exclude, title, re.I):
            continue
        if re.search(pattern, title, re.I) and _poly_season_ok(ev, season):
            return ev
    return None


# ── futures ──────────────────────────────────────────────────────────────────

def _team_title(kind: str, series: str, pattern: str | None, season: int, teams: dict, ids: list[str],
                kalshi: dict | None, pev: list[dict], exclude: str | None = None, kalshi_event: dict | None = None) -> dict:
    def mapper(label, code):
        return map_team(label, teams, code)
    sources, markets = {}, {}
    ev = kalshi_event or _kalshi_event(series, season, kalshi)
    if ev:
        sources["kalshi"] = parse_kalshi_field(ev, mapper)
        markets["kalshi"] = ev.get("event_ticker")
    if pattern:
        pe = _poly_find(pev, pattern, season, exclude)
        if pe:
            sources["polymarket"] = parse_poly_field(pe, mapper)
            markets["polymarket"] = pe.get("slug")
    return assemble(sources, ids, kind, markets)


def award_prices(season: int, kind: str, kalshi: dict | None = None, pev: list[dict] | None = None) -> dict:
    spec = AWARD_KINDS[kind]

    def mapper(label, code):
        lab = str(label or "").strip()
        if not lab or re.fullmatch(r"(player [a-z]{1,2}|other|field|tie.*|.*co-winners.*)", lab.lower()):
            return None
        return f"name:{lab}"
    sources, markets = {}, {}
    ev = _kalshi_event(spec[0], season, kalshi)
    if ev:
        sources["kalshi"] = parse_kalshi_field(ev, mapper)
        markets["kalshi"] = ev.get("event_ticker")
    excl = r"Rookie|Comeback|Coach" if kind in ("opoy", "dpoy", "mvp") else None
    if kind == "mvp":
        excl = r"Rookie|Comeback|Coach|Super Bowl MVP"
    pe = _poly_find(pev or [], spec[1], season, excl)
    if pe:
        sources["polymarket"] = parse_poly_field(pe, mapper)
        markets["polymarket"] = pe.get("slug")
    # pool "Joshua Allen" / "Josh Allen" style duplicates by folded name
    for src in sources.values():
        src["mid"] = {f"name:{_canon_name(k)}": v for k, v in src["mid"].items()}
        src["floor"] = {f"name:{_canon_name(k)}" for k in src["floor"]}
        src["eliminated"] = {f"name:{_canon_name(k)}" for k in src["eliminated"]}
        if src.get("winner"):
            src["winner"] = f"name:{_canon_name(src['winner'])}"
    return assemble_field(sources, kind, markets)


AWARD_MAX_TOTAL_LONG = 1.6      # fields of 20+ runners: Polymarket's longshot quotes add 0.2-0.5 of overround


def assemble_field(sources: dict[str, dict], kind: str, markets: dict) -> dict:
    """Award fields: each source de-vigged on its own (implied total within 0.8-1.3, or 0.8-1.6 for 20+ quoted
    runners), then the fair probabilities averaged over the sources that quote a runner and renormalised."""
    fair_by, reasons, winner = {}, {}, None
    for name, src in sources.items():
        winner = winner or src.get("winner")
        mid = {r: p for r, p in src["mid"].items() if r not in src["eliminated"]}
        tot = sum(mid.values())
        hi = AWARD_MAX_TOTAL_LONG if len(mid) >= 20 else 1.3
        if mid and 0.8 <= tot <= hi:
            fair_by[name] = {r: p / tot for r, p in mid.items()}
        else:
            reasons[name] = f"implied total {tot:.2f} over {len(mid)} quoted runners"
    base = {"kind": kind, "markets": markets or {}, "sources": sorted(sources),
            "by_source": {k: {r: round(p, 4) for r, p in v["mid"].items()} for k, v in sources.items()},
            "unmatched": sorted({u for v in sources.values() for u in v["unmatched"]}), "rejected": reasons}
    if winner:
        return {**base, "available": False, "reason": f"settled: {winner} won", "probs": {}, "winner": winner}
    if not fair_by:
        return {**base, "available": False, "reason": "; ".join(f"{k}: {v}" for k, v in reasons.items()) or "no market",
                "probs": {}}
    runners = {r for f in fair_by.values() for r in f}
    avg = {r: sum(f[r] for f in fair_by.values() if r in f) / sum(1 for f in fair_by.values() if r in f) for r in runners}
    tot = sum(avg.values())
    probs = dict(sorted(((r, round(v / tot, 5)) for r, v in avg.items()), key=lambda kv: -kv[1]))
    return {**base, "available": True, "reason": None, "probs": probs, "used": sorted(fair_by)}


def _canon_name(key: str) -> str:
    lab = key.split(":", 1)[1] if key.startswith("name:") else key
    return " ".join(w.capitalize() if w.islower() else w for w in lab.replace("’", "'").split())


def binary_team(season: int, series: str, pattern: str, teams: dict, kalshi: dict | None, pev: list[dict]) -> dict:
    """Per-team yes/no markets (make the playoffs): {"probs": {team: mean mid}, "by_source", "markets"}."""
    def mapper(label, code):
        return map_team(label, teams, code)
    srcs, markets = {}, {}
    ev = _kalshi_event(series, season, kalshi)
    if ev:
        srcs["kalshi"] = parse_kalshi_field(ev, mapper)
        markets["kalshi"] = ev.get("event_ticker")
    pe = _poly_find(pev, pattern, season)
    if pe:
        srcs["polymarket"] = parse_poly_field(pe, mapper)
        markets["polymarket"] = pe.get("slug")
    pooled: dict[str, list] = {}
    for v in srcs.values():
        for t, p in v["mid"].items():
            pooled.setdefault(t, []).append(p)
        for t in v["eliminated"]:
            pooled.setdefault(t, []).append(0.0)
        if v.get("winner"):
            pooled.setdefault(v["winner"], []).append(1.0)
    probs = {t: round(sum(v) / len(v), 4) for t, v in pooled.items()}
    return {"available": bool(probs), "probs": probs, "markets": markets,
            "by_source": {k: {t: round(p, 4) for t, p in v["mid"].items()} for k, v in srcs.items()},
            "unmatched": sorted({u for v in srcs.values() for u in v["unmatched"]})}


def win_totals(season: int, teams: dict, kalshi: dict | None = None, pev: list[dict] | None = None) -> dict:
    """{team: {"kalshi": {"ladder": {N: P(W >= N)}, "line", "p_over", "ticker"}, "polymarket": {...}}}"""
    out: dict[str, dict] = {}
    nxt, cur = _yys(season)
    for ev in _kalshi_series("KXNFLWINS", kalshi):
        tk = str(ev.get("event_ticker") or "")
        m = re.search(rf"-(?:{nxt}|{cur})([A-Z]+)$", tk)
        if not m:
            continue
        tid = map_team(str(ev.get("sub_title") or "").replace(f"{season}-{(season + 1) % 100:02d}", "").strip(), teams,
                       m.group(1))
        lad = parse_win_ladder(ev)
        if tid and lad:
            out.setdefault(tid, {})["kalshi"] = {**lad, "ticker": tk}
    for ev in pev or []:
        title = str(ev.get("title") or "")
        mm = re.search(r"Pro Football:\s*(.+?)\s+(\d{4})\s+Win Total", title)
        if not mm or int(mm.group(2)) != season or ev.get("closed"):
            continue
        tid = map_team(mm.group(1), teams)
        if not tid:
            continue
        lad = {}
        for mk in ev.get("markets") or []:
            lab = str(mk.get("groupItemTitle") or "")
            m2 = re.match(r"(\d+(?:\.5)?)\+", lab)
            p = cpm.poly_price(mk)
            if m2 and p is not None:
                lad[int(math.ceil(float(m2.group(1))))] = p
        if lad:
            ks = sorted(lad)
            run, mono = 1.0, {}
            for k in ks:
                run = min(run, lad[k])
                mono[k] = round(run, 4)
            best = min(ks, key=lambda k: abs(mono[k] - 0.5))
            out.setdefault(tid, {})["polymarket"] = {"ladder": mono, "line": best - 0.5, "p_over": mono[best],
                                                     "slug": ev.get("slug")}
    return out


def advance(season: int, teams: dict, pev: list[dict]) -> dict:
    out = {}
    for rnd, pat in (("DIV_AFC", r"AFC Team to advance to Divisional"), ("DIV_NFC", r"NFC Team to advance to Divisional"),
                     ("CON_AFC", r"advance to AFC Championship"), ("CON_NFC", r"advance to NFC Championship")):
        ev = _poly_find(pev, pat, season)
        if not ev:
            continue
        src = parse_poly_field(ev, lambda label, code: map_team(label, teams, code))
        probs = {t: round(p, 4) for t, p in src["mid"].items()}
        for t in src["eliminated"]:
            probs[t] = 0.0
        out[rnd] = {"probs": probs, "market": ev.get("slug"), "unmatched": src["unmatched"]}
    return out


def futures(season: int | None = None, store: dict | None = None, kalshi: dict | None = None,
            poly: list[dict] | None = None) -> dict:
    """{"champion": TITLE, "conference": {"AFC","NFC"}, "division": {div: TITLE}, "top_seed": {"AFC","NFC"},
    "playoffs": BINARY, "win_totals": {...}, "awards": {kind: TITLE}, "advance": {...}, "season", "generated_at"}.
    `kalshi` ({series: [events]}) and `poly` (Polymarket tag events) replace the network (tests). Never raises."""
    season = int(season or season_for())
    out: dict[str, Any] = {"season": season, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        teams = teams_info(season, store)
        pev = poly if poly is not None else poly_events()
        allt = sorted(teams)
        out["champion"] = _team_title("champion", "KXSB", TITLE_KINDS["champion"][1], season, teams, allt, kalshi, pev,
                                      exclude=r"AFC|NFC|Division|East|West|North|South")
        out["conference"] = {c: _team_title(c, TITLE_KINDS[c][0], TITLE_KINDS[c][1], season, teams,
                                            [t for t, v in teams.items() if v["conf"] == c] or allt, kalshi, pev,
                                            exclude=r"#1 Seed|advance")
                             for c in ("AFC", "NFC")}
        div = {}
        for d in DIVISIONS:
            series = "KXNFL" + d.replace(" ", "").upper()
            ids = [t for t, v in teams.items() if v["div"] == d] or allt
            div[d] = _team_title(d, series, rf"Pro Football: {d} Champion", season, teams, ids, kalshi, pev)
        out["division"] = div
        seeds = {}
        for c in ("AFC", "NFC"):
            evs = [e for e in _kalshi_series("KXNFL1SEED", kalshi) if re.search(rf"-{c}({_yys(season)[1]}|{_yys(season)[0]})$",
                                                                                 str(e.get("event_ticker") or ""))]
            seeds[c] = _team_title(f"{c}_1seed", "KXNFL1SEED", rf"{c} #1 Seed", season, teams,
                                   [t for t, v in teams.items() if v["conf"] == c] or allt, kalshi, pev,
                                   kalshi_event=evs[0] if evs else {"markets": []})
        out["top_seed"] = seeds
        out["playoffs"] = binary_team(season, "KXNFLPLAYOFF", r"Team to Make Postseason", teams, kalshi, pev)
        out["win_totals"] = win_totals(season, teams, kalshi, pev)
        out["awards"] = {k: award_prices(season, k, kalshi, pev) for k in AWARD_KINDS}
        out["advance"] = advance(season, teams, pev)
    except Exception as exc:  # noqa: BLE001
        logger.info("nfl futures failed: %s", exc)
        out["error"] = str(exc)
    return out


# ── per game ─────────────────────────────────────────────────────────────────

def american_to_p(ml) -> float | None:
    try:
        x = float(str(ml).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x == 0 or -100 < x < 100:
        return None
    return 100.0 / (x + 100.0) if x > 0 else -x / (-x + 100.0)


def devig_ml(home, away) -> float | None:
    ph, pa = american_to_p(home), american_to_p(away)
    if ph is None or pa is None:
        return None
    return _dv.normalise_pair(ph, pa)          # common/edge/devig.py


def _two_way(qa, qb):
    if qa is not None and qb is not None and qa + qb > 0:
        return qa / (qa + qb)
    if qa is not None:
        return qa
    if qb is not None:
        return 1.0 - qb
    return None


def _codes_pair(codes: str, teams: dict) -> tuple[str, str] | None:
    """Split "PITCLE" / "LARPHI" / "NYJCHI" into (away, home) team codes."""
    for k in range(2, len(codes) - 1):
        a, b = codes[:k], codes[k:]
        ta, tb = map_team(None, teams, a), map_team(None, teams, b)
        if ta and tb:
            return ta, tb
    return None


def _match(games: list[dict], away: str, home: str, d: date | None) -> dict | None:
    hit = [g for g in games if g.get("home") == home and g.get("away") == away]
    if not hit:
        hit = [g for g in games if {g.get("home"), g.get("away")} == {home, away}]
    if d is not None and len(hit) > 1:
        def dist(g):
            try:
                return abs((date.fromisoformat(str(g.get("date"))[:10]) - d).days)
            except ValueError:
                return 99
        hit.sort(key=dist)
    return hit[0] if hit else None


def _games_list(store: dict | None, games=None) -> list[dict]:
    if games is not None:
        try:
            return [{"game_id": r.game_id, "home": r.home, "away": r.away, "date": str(r.date)[:10], "week": int(r.week),
                     "lines": None} for r in games.itertuples(index=False)]
        except AttributeError:
            return list(games)
    return [dict(g, game_id=g.get("game_id") or k) for k, g in ((store or {}).get("games") or {}).items()]


def game_prices(season: int | None = None, store: dict | None = None, games=None, kalshi: dict | None = None,
                poly: list[dict] | None = None, window: tuple[date, date] | None = None) -> dict[str, dict]:
    """
    {game_id: {"home","away","p_home","basis","sources":[{"source","p_home","market"}],
               "spread": {"kalshi": {"home": {X: P(home wins by > X)}, "away": {...}}, "polymarket": {"home": {line: P}}},
               "total": {"kalshi": {X: P(total > X)}, "polymarket": {line: P(over)}},
               "team_total": {"kalshi": {"home": {X: P(> X)}, "away": {...}}},
               "book": {"spread_home","total","ml_home","ml_away","p_home"} (the store's line)}}
    for the season's games (optionally kickoffs within `window`). Never raises.
    """
    season = int(season or season_for())
    try:
        teams = teams_info(season, store)
        gl = _games_list(store, games)
        if window:
            gl = [g for g in gl if window[0].isoformat() <= str(g.get("date"))[:10] <= window[1].isoformat()]
        out: dict[str, dict] = {}

        def rec(g):
            gid = str(g["game_id"])
            if gid not in out:
                out[gid] = {"home": g["home"], "away": g["away"], "date": g.get("date"), "sources": [], "spread": {},
                            "total": {}, "team_total": {}, "book": None, "p_home": None, "basis": None}
            return out[gid]

        def ev_game(ev):
            tk = str(ev.get("event_ticker") or "")
            mm = re.search(r"-(\d{2}[A-Z]{3}\d{2})([A-Z]+)$", tk)
            if not mm:
                return None, None
            pair = _codes_pair(mm.group(2), teams)
            if not pair:
                return None, None
            d = kalshi_game_date(tk)
            return _match(gl, pair[0], pair[1], d), d
        for ev in _kalshi_series("KXNFLGAME", kalshi):
            g, _d = ev_game(ev)
            if not g:
                continue
            q = {}
            for mk in ev.get("markets") or []:
                tid = map_team(mk.get("yes_sub_title"), teams, _ticker_code(mk.get("ticker")))
                p = cpm.kalshi_price(mk)
                if tid and p is not None:
                    q[tid] = p
            ph = _two_way(q.get(g["home"]), q.get(g["away"]))
            if ph is not None:
                rec(g)["sources"].append({"source": "kalshi", "p_home": round(ph, 4), "market": ev.get("event_ticker")})
        for ev in _kalshi_series("KXNFLSPREAD", kalshi):
            g, _d = ev_game(ev)
            if not g:
                continue
            lad: dict[str, dict] = {}
            for mk in ev.get("markets") or []:
                code = re.sub(r"\d+$", "", _ticker_code(mk.get("ticker")) or "")
                tid = map_team(None, teams, code)
                p = cpm.kalshi_price(mk)
                try:
                    x = float(mk.get("floor_strike"))
                except (TypeError, ValueError):
                    continue
                if tid and p is not None:
                    lad.setdefault("home" if tid == g["home"] else "away", {})[x] = round(p, 4)
            if lad:
                rec(g)["spread"]["kalshi"] = {k: dict(sorted(v.items())) for k, v in lad.items()}
        for ev in _kalshi_series("KXNFLTOTAL", kalshi):
            g, _d = ev_game(ev)
            if not g:
                continue
            lad = {}
            for mk in ev.get("markets") or []:
                p = cpm.kalshi_price(mk)
                try:
                    x = float(mk.get("floor_strike"))
                except (TypeError, ValueError):
                    continue
                if p is not None:
                    lad[x] = round(p, 4)
            if lad:
                rec(g)["total"]["kalshi"] = dict(sorted(lad.items()))
        for ev in _kalshi_series("KXNFLTEAMTOTAL", kalshi):
            g, _d = ev_game(ev)
            if not g:
                continue
            lad = {}
            for mk in ev.get("markets") or []:
                code = re.sub(r"\d+$", "", _ticker_code(mk.get("ticker")) or "")
                tid = map_team(None, teams, code)
                p = cpm.kalshi_price(mk)
                try:
                    x = float(mk.get("floor_strike"))
                except (TypeError, ValueError):
                    continue
                if tid and p is not None:
                    lad.setdefault("home" if tid == g["home"] else "away", {})[x] = round(p, 4)
            if lad:
                rec(g)["team_total"]["kalshi"] = {k: dict(sorted(v.items())) for k, v in lad.items()}
        pg = poly if poly is not None else poly_games()
        for ev in pg or []:
            slug = str(ev.get("slug") or "")
            mm = re.fullmatch(r"nfl-([a-z]+)-([a-z]+)-(\d{4}-\d{2}-\d{2})", slug)
            if not mm or ev.get("closed"):
                continue
            ta, th = map_team(None, teams, mm.group(1).upper()), map_team(None, teams, mm.group(2).upper())
            if not ta or not th:
                continue
            g = _match(gl, ta, th, date.fromisoformat(mm.group(3)))
            if not g:
                continue
            r = rec(g)
            for mk in ev.get("markets") or []:
                smt = str(mk.get("sportsMarketType") or "")
                outs = mk.get("outcomes")
                if isinstance(outs, str):
                    try:
                        outs = json.loads(outs)
                    except ValueError:
                        outs = None
                p = cpm.poly_price(mk)
                if p is None or not outs or len(outs) != 2:
                    continue
                if smt == "moneyline":
                    o0 = map_team(outs[0], teams)
                    if o0 not in (g["home"], g["away"]):
                        continue
                    ph = p if o0 == g["home"] else 1.0 - p
                    r["sources"].append({"source": "polymarket", "p_home": round(ph, 4), "market": slug})
                elif smt == "spreads":
                    try:
                        line = float(mk.get("line"))
                    except (TypeError, ValueError):
                        continue
                    o0 = map_team(outs[0], teams)
                    if o0 not in (g["home"], g["away"]):
                        continue
                    side = "home" if o0 == g["home"] else "away"
                    r["spread"].setdefault("polymarket", {}).setdefault(side, {})[line] = round(p, 4)
                elif smt == "totals":
                    try:
                        line = float(mk.get("line"))
                    except (TypeError, ValueError):
                        continue
                    po = p if str(outs[0]).lower().startswith("over") else 1.0 - p
                    r["total"].setdefault("polymarket", {})[line] = round(po, 4)
        for g in gl:
            L = g.get("lines") or {}
            if not L:
                continue
            close = L.get("close") if isinstance(L.get("close"), dict) else {}
            src = {k: close.get(k, L.get(k)) for k in ("spread_home", "total", "ml_home", "ml_away")}
            ph = devig_ml(src.get("ml_home"), src.get("ml_away"))
            if any(v is not None for v in src.values()):
                r = rec(g)
                r["book"] = {**src, "p_home": round(ph, 4) if ph is not None else None,
                             "provider": L.get("src") or L.get("espn_src")}
        for r in out.values():
            pm = [x["p_home"] for x in r["sources"] if x["source"] in ("kalshi", "polymarket")]
            if pm:
                r["p_home"], r["basis"] = round(sum(pm) / len(pm), 4), "prediction_markets"
            elif r["book"] and r["book"].get("p_home") is not None:
                r["p_home"], r["basis"] = r["book"]["p_home"], "book_ml"
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("nfl game_prices failed: %s", exc)
        return {}


def edge(model_p, market_p):
    if model_p is None or market_p is None or market_p <= 0:
        return None
    return round(model_p / market_p - 1.0, 4)


def compare_titles(model: dict[str, float], title: dict) -> list[dict]:
    probs = (title or {}).get("probs") or {}
    rows = []
    for k in sorted(set(model) | set(probs), key=lambda x: -(model.get(x) or 0)):
        m, q = model.get(k), probs.get(k)
        rows.append({"id": k, "model": m, "market": q, "edge": edge(m, q) if title.get("available") else None})
    return rows
