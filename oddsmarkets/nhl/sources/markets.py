"""
NHL prices from Kalshi and Polymarket, mapped to NHL tri-codes and player names.

What exists (surveyed 2026-10-01; fixture tests/nhl/fixtures/markets_c.json)

    Kalshi (/events?series_ticker=..., nested markets; event suffix = the season's end year, -27 for 2026-27)
        KXNHL-27                  Stanley Cup ("2026-27 Stanley Cup Finals Winner"), 32 markets, ticker suffix = code
        KXNHLEAST-27 / KXNHLWEST-27              conference champions (16 each)
        KXNHLATLANTIC-27, KXNHLMETROPOLITAN-27, KXNHLCENTRAL-27, KXNHLPACIFIC-27   division winners (8 each)
        KXNHLPLAYOFF-27           make the playoffs, per-team yes/no (32)
        KXNHLPRES-27              Presidents' Trophy (32)
        KXNHLSEASONPTS-27ANA      regular-season points, one event per team, "N+ points" ladder (floor_strike N,
                                  strike_type greater_or_equal; 70..115 by 5)
        KXNHLHART-27 (28 runners), KXNHLNORRIS-27 (30); KXNHLVEZINA / CALDER / ROSS / RICHARD / SELKE had no open
                                  event on 2026-10-01 and are parsed the same way when they list
        KXNHLGAME-26OCT01BUFCBJ   game winner, one market per team (ticker suffix = code; "Buffalo vs Columbus")
        KXNHLSPREAD-26OCT01BUFCBJ "<Team> wins by over X goals" (X = 1.5, 2.5; ticker suffix code + ceil(X))
        KXNHLTOTAL-26OCT01BUFCBJ  "Over X goals scored" ladder (1.5 .. 9.5)
        KXNHLOT-26OCT01BUFCBJ     "Game goes to overtime" (one market)
        Kalshi codes are NHL tri-codes except LA (LAK), SJ (SJS), NJ (NJD), TB (TBL).
    Polymarket
        tag "nhl" (224 open events over three pages of 100): "NHL: 2027 Champion", "NHL: 2027 Eastern / Western
        Conference Champion", "NHL Presidents' Trophy Winner", "Which teams will make the NHL Playoffs?",
        "NHL: Teams to Record 80+ / 90+ / 100+ / 110+ Points" (per-team yes / no), "NHL Hart Memorial Trophy Winner",
        Vezina, James Norris, Calder ("NHL: 2026-27 Calder Trophy"), Art Ross, Maurice 'Rocket' Richard, Frank J.
        Selke, Ted Lindsay, Jack Adams, "NHL Playoffs: Team to advance to Eastern Conference Finals", "... Eastern
        Conference Team to advance to Second Round", player props (dropped) and the per-game events.
        Games: /events?series_id=10346, slug "nhl-<a>-<b>-YYYY-MM-DD" (codes lower-case; las = VGK, mon = MTL,
        cal = CGY, utah = UTA), markets moneyline (outcomes nicknames, "Utah"), spreads ("Spread: Blue Jackets
        (-1.5)", price = first outcome covers `line`), totals (`line` 4.5 .. 7.5, outcomes Over / Under).

Prices and the thin-market rule are Hardwood's (basketball/sources/markets.py): a price is the midpoint of a live
two-sided quote ((bid + ask) / 2, 0 < bid <= ask < 1, ask - bid <= 0.12; a last trade is never a price); team field
markets are pooled across sources, published only when at least max(4, half the field) runners are accounted for and
the implied total is within 0.8-1.3, then de-vigged multiplicatively. Award fields are de-vigged per source (implied
total 0.8-1.3, or up to 1.6 with 20+ quoted runners) and averaged across sources. Two-way game markets are de-vigged
across their two sides; Kalshi spread / total / OT ladders are published as quoted mids.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timezone
from typing import Any

from oddsmarkets.basketball.sources.markets import (  # noqa: F401  (sport-neutral parsers)
    _no_bid_floor,
    assemble,
    kalshi_game_date,
    parse_kalshi_field,
    parse_poly_field,
)
from oddsmarkets.common import prediction_markets as cpm
from oddsmarkets.common.edge import devig as _dv

logger = logging.getLogger(__name__)

POLY_TAG = "nhl"
POLY_GAMES_SERIES = 10346
DIVISIONS = ("Atlantic", "Metropolitan", "Central", "Pacific")
CONFERENCES = {"Eastern": ("KXNHLEAST", r"\b20\d\d Eastern Conference Champion"),
               "Western": ("KXNHLWEST", r"\b20\d\d Western Conference Champion")}
AWARD_KINDS = {
    "hart": ("KXNHLHART", r"Hart Memorial Trophy|\bHart Trophy"),
    "vezina": ("KXNHLVEZINA", r"Vezina"),
    "norris": ("KXNHLNORRIS", r"Norris"),
    "calder": ("KXNHLCALDER", r"Calder"),
    "ross": ("KXNHLROSS", r"Art Ross"),
    "richard": ("KXNHLRICHARD", r"Rocket.? Richard"),
    "selke": ("KXNHLSELKE", r"Selke"),
}
FUTURE_WORDS = ("champion", "trophy", "award", "make the nhl playoffs", "points", "advance to", "winner")
POINT_LADDER_RE = r"Teams to Record (\d+)\+ Points"

# indirection so tests can swap the network for canned payloads
kalshi_events = cpm.kalshi_events
polymarket_event = cpm.polymarket_event


def season_for(d: date | None = None) -> int:
    """NHL season id (20262027) in progress or next to start: canon's rule (turns over on 1 July)."""
    d = d or datetime.now(timezone.utc).date()
    y = d.year if d.month >= 7 else d.year - 1
    return y * 10000 + y + 1


def _end_year(season: int) -> int:
    s = int(season)
    return s % 10000 if s > 9999 else s + 1


def _yy(season: int) -> str:
    return f"{_end_year(season) % 100:02d}"


# ── teams ────────────────────────────────────────────────────────────────────

CODE_ALIASES = {"LA": "LAK", "SJ": "SJS", "NJ": "NJD", "TB": "TBL", "UTAH": "UTA", "LAS": "VGK", "VEG": "VGK", "MON": "MTL",
                "CAL": "CGY", "WAS": "WSH", "ARZ": "ARI", "PHX": "ARI", "NAS": "NSH", "CLB": "CBJ", "WIN": "WPG"}


def teams_info(season: int, store: dict | None = None) -> dict[str, dict]:
    """{abbr: {"name","nick","loc","conf","div"}} from the store's teams, else builder C's canon fallback."""
    out = {}
    sti = (store or {}).get("teams") or {}
    if isinstance(sti, dict) and sti:
        for t, v in sti.items():
            v = v or {}
            out[str(t)] = {"name": v.get("name") or t, "conf": v.get("conference"), "div": v.get("division")}
    if not out:
        try:
            from oddsmarkets.nhl.models import _cdata as D
            for t, v in D.teams_for(season).items():
                out[t] = {"name": v.get("name") or t, "conf": v.get("conference"), "div": v.get("division")}
        except Exception:  # noqa: BLE001
            pass
    for t, v in out.items():
        name = str(v["name"])
        parts = name.split()
        two = " ".join(parts[-2:]) if len(parts) >= 3 else None
        nick = two if two in ("Maple Leafs", "Red Wings", "Blue Jackets", "Golden Knights") else parts[-1]
        v["nick"] = nick
        v["loc"] = name[: -len(nick)].strip() if name.endswith(nick) else name
    return out


def map_team(label: str | None, teams: dict[str, dict], code: str | None = None) -> str | None:
    """Tri-code for a market's team code / label ("Los Angeles Kings", "LA Kings", "Utah", "Blue Jackets"), or None."""
    if not teams:
        return None
    if code:
        c = str(code).upper()
        c = CODE_ALIASES.get(c, c)
        if c in teams:
            return c
    if not label:
        return None
    lab = re.sub(r"\s*\(\d{4}-\d{2}\)\s*$", "", str(label)).strip()
    m = re.fullmatch(r"([A-Z]{2,4})\s+(.+)", lab)                     # "LA Kings", "ANA Ducks"
    if m:
        c = CODE_ALIASES.get(m.group(1), m.group(1))
        if c in teams:
            return c
    fl = cpm.fold(lab)
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

def _kalshi_series(series: str, kalshi: dict | None) -> list[dict]:
    if kalshi is not None:
        return list(kalshi.get(series) or [])
    return kalshi_events(series) or []


def _kalshi_event(series: str, season: int, kalshi: dict | None) -> dict | None:
    yy = _yy(season)
    for e in _kalshi_series(series, kalshi):
        if re.search(rf"-{yy}$", str(e.get("event_ticker") or "")):
            return e
    return None


def poly_events(pages: int = 6, closed: bool = False) -> list[dict]:
    """Polymarket futures under tag "nhl" (paged by offset, 100 a page; games and player props dropped)."""
    out, seen = [], set()
    for k in range(pages):
        rows = cpm._get(f"{cpm.GAMMA}/events", {"tag_slug": POLY_TAG, "closed": "true" if closed else "false",
                                               "limit": 100, "offset": 100 * k}) or []
        if not isinstance(rows, list) or not rows:
            break
        for e in rows:
            t = str(e.get("title") or "").lower()
            slug = str(e.get("slug") or "")
            if re.fullmatch(r"nhl-[a-z]+-[a-z]+-\d{4}-\d{2}-\d{2}", slug):
                continue
            if any(w in t for w in FUTURE_WORDS) and slug not in seen:
                seen.add(slug)
                out.append(e)
        if len(rows) < 100:
            break
    return out


def poly_games(closed: bool = False) -> list[dict]:
    rows = cpm._get(f"{cpm.GAMMA}/events", {"series_id": POLY_GAMES_SERIES, "closed": "true" if closed else "false",
                                           "limit": 100})
    return rows if isinstance(rows, list) else []


def _poly_season_ok(ev: dict, season: int) -> bool:
    title = str(ev.get("title") or "")
    y1, y2 = _end_year(season) - 1, _end_year(season)
    if f"{y1}-{y2 % 100:02d}" in title or str(y2) in title:
        return True
    if re.search(r"\b20\d\d\b", title):
        return False
    end = str(ev.get("endDate") or "")[:4]
    return end in (str(y1), str(y2))


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

def _team_title(kind: str, series: str | None, pattern: str | None, season: int, teams: dict, ids: list[str],
                kalshi: dict | None, pev: list[dict], exclude: str | None = None) -> dict:
    def mapper(label, code):
        return map_team(label, teams, code)
    sources, markets = {}, {}
    ev = _kalshi_event(series, season, kalshi) if series else None
    if ev:
        sources["kalshi"] = parse_kalshi_field(ev, mapper)
        markets["kalshi"] = ev.get("event_ticker")
    if pattern:
        pe = _poly_find(pev, pattern, season, exclude)
        if pe:
            sources["polymarket"] = parse_poly_field(pe, mapper)
            markets["polymarket"] = pe.get("slug")
    return assemble(sources, ids, kind, markets)


def binary_team(season: int, series: str | None, pattern: str | None, teams: dict, kalshi: dict | None, pev: list[dict]) -> dict:
    """Per-team yes/no markets (make the playoffs): {"available","probs": {team: mean mid},"by_source","markets"}."""
    def mapper(label, code):
        return map_team(label, teams, code)
    srcs, markets = {}, {}
    ev = _kalshi_event(series, season, kalshi) if series else None
    if ev:
        srcs["kalshi"] = parse_kalshi_field(ev, mapper)
        markets["kalshi"] = ev.get("event_ticker")
    pe = _poly_find(pev, pattern, season) if pattern else None
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


def parse_points_ladder(event: dict) -> dict | None:
    """{"ladder": {N: P(points >= N)} (non-increasing), "line", "p_over"} from one KXNHLSEASONPTS event."""
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
    return _mono(lad)


def _mono(lad: dict) -> dict:
    ks = sorted(lad)
    run, mono = 1.0, {}
    for k in ks:
        run = min(run, lad[k])
        mono[k] = round(run, 4)
    best = min(ks, key=lambda k: abs(mono[k] - 0.5))
    return {"ladder": mono, "line": best - 0.5, "p_over": mono[best]}


def points_totals(season: int, teams: dict, kalshi: dict | None = None, pev: list[dict] | None = None) -> dict:
    """{team: {"kalshi": {"ladder", "line", "p_over", "ticker"}, "polymarket": {"ladder": {80: p, 90: p, ...}}}}"""
    out: dict[str, dict] = {}
    yy = _yy(season)
    for ev in _kalshi_series("KXNHLSEASONPTS", kalshi):
        tk = str(ev.get("event_ticker") or "")
        m = re.search(rf"-{yy}([A-Z]+)$", tk)
        if not m:
            continue
        tid = map_team(str(ev.get("sub_title") or ""), teams, m.group(1))
        lad = parse_points_ladder(ev)
        if tid and lad:
            out.setdefault(tid, {})["kalshi"] = {**lad, "ticker": tk}
    poly: dict[str, dict] = {}
    for ev in pev or []:
        mm = re.search(POINT_LADDER_RE, str(ev.get("title") or ""))
        if not mm or ev.get("closed") or not _poly_season_ok(ev, season):
            continue
        n = int(mm.group(1))
        src = parse_poly_field(ev, lambda label, code: map_team(label, teams, code))
        for t, p in src["mid"].items():
            poly.setdefault(t, {})[n] = p
        for t in src["eliminated"]:
            poly.setdefault(t, {})[n] = 0.0
        if src.get("winner"):
            poly.setdefault(src["winner"], {})[n] = 1.0
    for t, lad in poly.items():
        out.setdefault(t, {})["polymarket"] = {**_mono(lad), "events": "Teams to Record N+ Points"}
    return out


AWARD_MAX_TOTAL_LONG = 1.6


def assemble_field(sources: dict[str, dict], kind: str, markets: dict) -> dict:
    """Award fields: each source de-vigged on its own (implied total 0.8-1.3, or 0.8-1.6 with 20+ quoted runners),
    then the fair probabilities averaged over the sources that quote a runner and renormalised."""
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
    pooled: dict[str, list] = {}
    for v in sources.values():
        for r, q in v["mid"].items():
            pooled.setdefault(r, []).append(q)
    base["mid"] = dict(sorted(((r, round(sum(q) / len(q), 4)) for r, q in pooled.items()), key=lambda kv: -kv[1]))
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


AWARD_MIN_BID = 0.01


def strict_mid(bid, ask) -> float | None:
    """Award runners: a price needs a real bid (>= 1c) and a spread no wider than max(3c, the mid) (capped at 12c);
    Polymarket lists most of an award field at 0.1c bid / 10c ask, which is not a price."""
    b, a = cpm._f(bid), cpm._f(ask)
    if b is None or a is None or b < AWARD_MIN_BID or a <= b - 1e-12 or a >= 1:
        return None
    m = (a + b) / 2
    return m if (a - b) <= min(cpm.MAX_SPREAD, max(0.03, m)) else None


def _strict(src: dict, event: dict, kalshi: bool, mapper) -> dict:
    """Re-price a parsed award source with `strict_mid`; runners that lose their price count as floor."""
    for m in (event or {}).get("markets") or []:
        label = str((m.get("yes_sub_title") or m.get("subtitle")) if kalshi else m.get("groupItemTitle") or "")
        rid = mapper(label, None)
        if not rid or rid not in src["mid"]:
            continue
        q = strict_mid(m.get("yes_bid_dollars"), m.get("yes_ask_dollars")) if kalshi else strict_mid(m.get("bestBid"), m.get("bestAsk"))
        if q is None:
            src["mid"].pop(rid, None)
            src["floor"].add(rid)
        else:
            src["mid"][rid] = q
    return src


def award_prices(season: int, kind: str, kalshi: dict | None = None, pev: list[dict] | None = None) -> dict:
    """One award field as {"probs": {"name:<Player>": p}, ...}; names are mapped to player ids by awards.py."""
    spec = AWARD_KINDS[kind]

    def mapper(label, code):
        lab = str(label or "").strip()
        if not lab or re.fullmatch(r"(player [a-z]{1,2}|other|field|tie.*|.*co-winners.*|another player)", lab.lower()):
            return None
        return f"name:{lab}"
    sources, markets = {}, {}
    ev = _kalshi_event(spec[0], season, kalshi)
    if ev:
        sources["kalshi"] = _strict(parse_kalshi_field(ev, mapper), ev, True, mapper)
        markets["kalshi"] = ev.get("event_ticker")
    pe = _poly_find(pev or [], spec[1], season, r"Ted Lindsay|Jack Adams")
    if pe:
        sources["polymarket"] = _strict(parse_poly_field(pe, mapper), pe, False, mapper)
        markets["polymarket"] = pe.get("slug")
    for src in sources.values():
        src["mid"] = {f"name:{_canon_name(k)}": v for k, v in src["mid"].items()}
        src["floor"] = {f"name:{_canon_name(k)}" for k in src["floor"]}
        src["eliminated"] = {f"name:{_canon_name(k)}" for k in src["eliminated"]}
        if src.get("winner"):
            src["winner"] = f"name:{_canon_name(src['winner'])}"
    return assemble_field(sources, kind, markets)


def advance(season: int, teams: dict, pev: list[dict]) -> dict:
    """Polymarket round-advancement fields: {"r2_east","r2_west","cf_east","cf_west": {"probs","market"}}."""
    out = {}
    for rnd, pat in (("r2_east", r"Eastern Conference Team to advance to Second Round"),
                     ("r2_west", r"Western Conference Team to advance to Second Round"),
                     ("cf_east", r"Team to advance to Eastern Conference Finals"),
                     ("cf_west", r"Team to advance to Western Conference Finals")):
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
    """{"champion": TITLE, "conference": {"Eastern","Western"}, "division": {div: TITLE}, "presidents": TITLE,
    "playoffs": BINARY, "points": {...}, "awards": {kind: FIELD}, "advance": {...}, "season", "generated_at"}.
    `kalshi` ({series: [events]}) and `poly` (Polymarket tag events) replace the network (tests). Never raises."""
    season = int(season or season_for())
    out: dict[str, Any] = {"season": season, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        teams = teams_info(season, store)
        pev = poly if poly is not None else poly_events()
        allt = sorted(teams)
        out["champion"] = _team_title("champion", "KXNHL", r"^NHL: 20\d\d Champion$", season, teams, allt, kalshi, pev,
                                      exclude=r"Conference|Division")
        out["conference"] = {c: _team_title(c, spec[0], spec[1], season, teams,
                                            [t for t, v in teams.items() if str(v.get("conf") or "").startswith(c[:4])] or allt,
                                            kalshi, pev) for c, spec in CONFERENCES.items()}
        out["division"] = {d: _team_title(d, "KXNHL" + d.upper(), rf"\b{d} Division (Winner|Champion)", season, teams,
                                          [t for t, v in teams.items() if v.get("div") == d] or allt, kalshi, pev)
                           for d in DIVISIONS}
        out["presidents"] = _team_title("presidents", "KXNHLPRES", r"Presidents.? Trophy", season, teams, allt, kalshi, pev)
        out["playoffs"] = binary_team(season, "KXNHLPLAYOFF", r"make the NHL Playoffs", teams, kalshi, pev)
        out["points"] = points_totals(season, teams, kalshi, pev)
        out["awards"] = {k: award_prices(season, k, kalshi, pev) for k in AWARD_KINDS}
        out["advance"] = advance(season, teams, pev)
    except Exception as exc:  # noqa: BLE001
        logger.info("nhl futures failed: %s", exc)
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
    """"BUFCBJ" / "FLALA" / "LASJ" -> (first, second) tri-codes."""
    for k in range(2, len(codes) - 1):
        a, b = codes[:k], codes[k:]
        ta, tb = map_team(None, teams, a), map_team(None, teams, b)
        if ta and tb and ta != tb:
            return ta, tb
    return None


def _match(games: list[dict], a: str, b: str, d: date | None) -> dict | None:
    hit = [g for g in games if {g.get("home"), g.get("away")} == {a, b}]
    if d is not None:
        def dist(g):
            try:
                return abs((date.fromisoformat(str(g.get("date"))[:10]) - d).days)
            except ValueError:
                return 99
        hit = [g for g in hit if dist(g) <= 1]
        hit.sort(key=dist)
    return hit[0] if hit else None


def _games_list(store: dict | None, games=None) -> list[dict]:
    if games is not None:
        try:
            return [{"game_id": str(r.game_id), "home": r.home, "away": r.away, "date": str(r.date)[:10], "lines": None}
                    for r in games.itertuples(index=False)]
        except AttributeError:
            return list(games)
    g = (store or {}).get("games") or {}
    if isinstance(g, dict):
        return [dict(v, game_id=str(v.get("game_id") or k)) for k, v in g.items()]
    return [dict(v) for v in g]


def _strike(mk) -> float | None:
    try:
        return float(mk.get("floor_strike"))
    except (TypeError, ValueError):
        return None


def game_prices(season: int | None = None, store: dict | None = None, games=None, kalshi: dict | None = None,
                poly: list[dict] | None = None, window: tuple[date, date] | None = None) -> dict[str, dict]:
    """
    {game_id: {"home","away","date","p_home","basis","sources":[{"source","p_home","market"}],
               "spread": {"kalshi": {"home": {X: P(home wins by > X)}, "away": {...}}, "polymarket": {"home": {line: P}}},
               "total": {"kalshi": {X: P(total > X)}, "polymarket": {line: P(over)}},
               "ot": {"kalshi": P(overtime)}, "book": {...}}}
    for the season's games (optionally within `window`). Never raises.
    """
    season = int(season or season_for())
    try:
        teams = teams_info(season, store)
        gl = _games_list(store, games)
        for g in gl:
            g["home"], g["away"] = map_team(None, teams, g.get("home")) or g.get("home"), map_team(None, teams, g.get("away")) or g.get("away")
        if window:
            gl = [g for g in gl if window[0].isoformat() <= str(g.get("date"))[:10] <= window[1].isoformat()]
        out: dict[str, dict] = {}

        def rec(g):
            gid = str(g["game_id"])
            if gid not in out:
                out[gid] = {"home": g["home"], "away": g["away"], "date": str(g.get("date"))[:10], "sources": [], "spread": {},
                            "total": {}, "ot": {}, "book": None, "p_home": None, "basis": None}
            return out[gid]

        def ev_game(ev):
            tk = str(ev.get("event_ticker") or "")
            mm = re.search(r"-(\d{2}[A-Z]{3}\d{2})([A-Z]+)$", tk)
            if not mm:
                return None
            pair = _codes_pair(mm.group(2), teams)
            if not pair:
                return None
            return _match(gl, pair[0], pair[1], kalshi_game_date(tk))
        for ev in _kalshi_series("KXNHLGAME", kalshi):
            g = ev_game(ev)
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
        for ev in _kalshi_series("KXNHLSPREAD", kalshi):
            g = ev_game(ev)
            if not g:
                continue
            lad: dict[str, dict] = {}
            for mk in ev.get("markets") or []:
                code = re.sub(r"\d+$", "", _ticker_code(mk.get("ticker")) or "")
                tid = map_team(None, teams, code)
                p, x = cpm.kalshi_price(mk), _strike(mk)
                if tid and p is not None and x is not None:
                    lad.setdefault("home" if tid == g["home"] else "away", {})[x] = round(p, 4)
            if lad:
                rec(g)["spread"]["kalshi"] = {k: dict(sorted(v.items())) for k, v in lad.items()}
        for ev in _kalshi_series("KXNHLTOTAL", kalshi):
            g = ev_game(ev)
            if not g:
                continue
            lad = {}
            for mk in ev.get("markets") or []:
                p, x = cpm.kalshi_price(mk), _strike(mk)
                if p is not None and x is not None:
                    lad[x] = round(p, 4)
            if lad:
                rec(g)["total"]["kalshi"] = dict(sorted(lad.items()))
        for ev in _kalshi_series("KXNHLOT", kalshi):
            g = ev_game(ev)
            if not g:
                continue
            for mk in ev.get("markets") or []:
                p = cpm.kalshi_price(mk)
                if p is not None:
                    rec(g)["ot"]["kalshi"] = round(p, 4)
        pg = poly if poly is not None else poly_games()
        for ev in pg or []:
            slug = str(ev.get("slug") or "")
            mm = re.fullmatch(r"nhl-([a-z]+)-([a-z]+)-(\d{4}-\d{2}-\d{2})", slug)
            if not mm or ev.get("closed"):
                continue
            ta, tb = map_team(None, teams, mm.group(1).upper()), map_team(None, teams, mm.group(2).upper())
            if not ta or not tb:
                continue
            g = _match(gl, ta, tb, date.fromisoformat(mm.group(3)))
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
                    r["sources"].append({"source": "polymarket", "p_home": round(p if o0 == g["home"] else 1.0 - p, 4),
                                         "market": slug})
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
            try:
                from oddsmarkets.nhl.models._cdata import line_fields
                lf = line_fields(L)
            except Exception:  # noqa: BLE001
                continue
            ph = devig_ml(lf.get("ml_home"), lf.get("ml_away"))
            if ph is not None or lf.get("total_line") is not None:
                rec(g)["book"] = {"ml_home": lf.get("ml_home"), "ml_away": lf.get("ml_away"), "puck_line": lf.get("pl_home"),
                                  "total": lf.get("total_line"), "p_home": round(ph, 4) if ph is not None else None,
                                  "provider": lf.get("book")}
        for r in out.values():
            pm = [x["p_home"] for x in r["sources"] if x["source"] in ("kalshi", "polymarket")]
            if pm:
                r["p_home"], r["basis"] = round(sum(pm) / len(pm), 4), "prediction_markets"
            elif r["book"] and r["book"].get("p_home") is not None:
                r["p_home"], r["basis"] = r["book"]["p_home"], "book_ml"
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("nhl game_prices failed: %s", exc)
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
        rows.append({"id": k, "model": m, "market": q, "edge": edge(m, q) if (title or {}).get("available") else None})
    return rows
