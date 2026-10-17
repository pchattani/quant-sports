"""
F1 prices from Kalshi and Polymarket, mapped to Jolpica driverId / constructorId.

What exists (surveyed 2026-09-30; Kalshi /series?category=Sports, Polymarket
public-search and the `f1` / `formula1` tags)

    Kalshi (series tickers, tag "Motorsport")
        KXF1               F1 Drivers Champion, one event per season (KXF1-26), one market per driver   -> title_prices("drivers")
        KXF1CONSTRUCTORS   F1 Constructors Champion (KXF1CONSTRUCTORS-26), one market per team          -> title_prices("constructors")
        KXF1RACE           race winner, one event per Grand Prix (KXF1RACE-BAH26 ...), listed ~a week out -> race_winner_prices
        KXF1H2H            "F1 Matchup: Verstappen vs Hamilton", one event per pairing per race
                           (KXF1H2H-BRIGP26VERHAM); none open on the survey date                        -> h2h_prices
        also, not used here: KXF1RACEPODIUM, KXF1RACETOP5, KXF1RACETOP10, KXF1RACETOPX, KXF1TOP5, KXF1TOP10,
        KXF1TOPCONSTRUCTOR, KXF1POLE, KXF1POLEPOSITION, KXF1QUALIFY, KXF1FASTLAP, KXF1FASTESTLAP,
        KXF1BIGGESTMOVER, KXF1RETIRE, KXF1RACESPRINT, KXF1SPRINTTOP5/10, KXF1SPRINTPOLE, KXF1SPRINTFASTLAP,
        KXF1SPRINTTOPCONSTRUCTOR, KXF1NEXTTEAM, KXF1DELAY, KXF1OCCUR, KXF1CHINA, KXUSAF1, KXAFRICAF1, KXF1ACTION
    Polymarket (tag slug "f1")
        2026-f1-drivers-champion      F1 Drivers' Champion (one yes/no market per driver; eliminated
                                      drivers' markets are closed and settled No)
        f1-constructors-champion      F1 Constructors' Champion
        f1-<gp>-grand-prix-winner-<date>   "<GP>: Driver Winner", listed around race week
        f1-<gp>-grand-prix-h2h-<date>      "<GP>: Head-to-Head", binary "Who will finish higher: A or B?"
        f1-will-<a>-finish-ahead-of-<b>-in-the-2026-drivers-championship   season head-to-head
        also per race: driver-podium, pole, fastest lap, constructor scores 1st, safety car, red flag, practice.

Prices
    A price is the midpoint of a live two-sided quote, (bid + ask) / 2, accepted only when
    0 < bid <= ask < 1 and ask - bid <= 0.12 (football's `_mid`); a last trade is never a
    price. Each source's mids are averaged per runner across sources (the consensus),
    then de-vigged across the field with `devig` (multiplicative: p_i = m_i / sum_j m_j).

Thin-market rule (as football, with one F1 adaptation)
    A field market is published only when at least max(4, half the field) runners are
    *accounted for* and the implied total of the two-sided mids is within 0.8-1.3.
    Accounted for = a two-sided quote, or a runner the market has written off: a
    Polymarket runner market closed and settled No (mathematically eliminated), or a
    no-bid quote with ask <= FLOOR_ASK (0.02). Late in a one-sided season most of the
    field trades only at "no bid / 1c ask", which says "under 1%", not "unpriced";
    those runners get probability 0 in `probs` and are listed under `floor`. Their
    floor is never used as a price.

Names
    Drivers: an F1 alias table (Polymarket's "Jr." for Sainz, "Kimi" for Antonelli), then
    the three-letter code, then `best_match` over full names, then over family names.
    Constructors: an alias table (Racing Bulls -> rb, Red Bull Racing -> red_bull, Mercedes
    AMG -> mercedes, Kick Sauber -> sauber ...), then `best_match` over names with "F1 Team"
    stripped. Unmatched labels are reported, never guessed.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from oddsmarkets.common import prediction_markets as cpm
from oddsmarkets.common.markets import devig
from oddsmarkets.f1 import store as st

logger = logging.getLogger(__name__)

KALSHI_SERIES = {"drivers": "KXF1", "constructors": "KXF1CONSTRUCTORS", "race": "KXF1RACE", "h2h": "KXF1H2H"}
POLY_TITLE_SLUGS = {"drivers": ("{year}-f1-drivers-champion", "f1-drivers-champion"),
                    "constructors": ("f1-constructors-champion", "{year}-f1-constructors-champion")}
POLY_TAG = "f1"
FLOOR_ASK = 0.02
MIN_TOTAL, MAX_TOTAL = 0.8, 1.3
DATE_WINDOW_DAYS = 3

DRIVER_ALIASES = {"jr": "sainz", "sainz jr": "sainz", "carlos sainz jr": "sainz", "kimi": "antonelli",
                  "kimi antonelli": "antonelli", "andrea kimi antonelli": "antonelli", "checo": "perez",
                  "checo perez": "perez", "max": "max_verstappen", "verstappen": "max_verstappen",
                  "lindblad": "arvid_lindblad", "magnussen": "kevin_magnussen", "schumacher": "mick_schumacher"}
CONSTRUCTOR_ALIASES = {"racing bulls": "rb", "visa cash app rb": "rb", "vcarb": "rb", "rb": "rb", "alphatauri": "alphatauri",
                       "red bull racing": "red_bull", "red bull": "red_bull", "oracle red bull racing": "red_bull",
                       "mercedes amg": "mercedes", "mercedes amg motorsport": "mercedes", "mercedes amg petronas": "mercedes",
                       "kick sauber": "sauber", "stake": "sauber", "sauber": "sauber", "audi f1": "audi", "audi": "audi",
                       "haas": "haas", "moneygram haas": "haas", "alpine": "alpine", "bwt alpine": "alpine",
                       "aston martin aramco": "aston_martin", "cadillac": "cadillac"}
_TEAM_WORDS = {"f1", "team", "formula", "one"}

# indirection so tests can swap the network for canned payloads
kalshi_events = cpm.kalshi_events
polymarket_event = cpm.polymarket_event
polymarket_tag_events = cpm.polymarket_tag_events


# ── the field ────────────────────────────────────────────────────────────────

def _season() -> int:
    return datetime.now(timezone.utc).year


def field(kind: str, year: int | None = None, store: dict | None = None) -> dict[str, dict]:
    """{id: info} for the season's drivers or constructors (those that took part, else the store's lists)."""
    s = store if store is not None else st.load(year or _season())
    key = "drivers" if kind in ("drivers", "race", "h2h") else "constructors"
    col = "driver" if key == "drivers" else "constructor"
    seen = {r.get(col) for race in (s.get("races") or {}).values()
            for r in (race.get("results") or []) + (race.get("qualifying") or []) if r.get(col)}
    reg = s.get(key) or {}
    ids = [i for i in reg if i in seen] or list(reg)
    return {i: reg.get(i) or {} for i in ids}


def _strip_team(name: str) -> str:
    return " ".join(t for t in cpm.fold(name).split() if t not in _TEAM_WORDS)


def map_driver(label: str, drivers: dict[str, dict]) -> str | None:
    """Jolpica driverId for a market's driver label, or None when unsure."""
    if not label or not drivers:
        return None
    key = cpm.fold(label)
    alias = DRIVER_ALIASES.get(key)
    if alias and alias in drivers:
        return alias
    text = str(label).strip()
    if re.fullmatch(r"[A-Z]{3}", text):
        hit = [d for d, i in drivers.items() if str(i.get("code") or "").upper() == text]
        if len(hit) == 1:
            return hit[0]
    full = {f"{i.get('given') or ''} {i.get('family') or ''}".strip() or d: d for d, i in drivers.items()}
    m = cpm.best_match(label, list(full))
    if m:
        return full[m]
    fam = {}
    for d, i in drivers.items():
        f = str(i.get("family") or "").strip()
        if f:
            fam.setdefault(f, []).append(d)
    fam = {f: ds[0] for f, ds in fam.items() if len(ds) == 1}
    m = cpm.best_match(label.split()[-1] if " " in label else label, list(fam), floor=0.8)
    if m:
        return fam[m]
    return None


def map_constructor(label: str, teams: dict[str, dict]) -> str | None:
    """Jolpica constructorId for a market's team label, or None when unsure."""
    if not label or not teams:
        return None
    key = cpm.fold(label)
    for k in (key, _strip_team(label)):
        alias = CONSTRUCTOR_ALIASES.get(k)
        if alias and alias in teams:
            return alias
    if key.replace(" ", "_") in teams:
        return key.replace(" ", "_")
    names = {}
    for c, i in teams.items():
        names[_strip_team(i.get("name") or c) or c] = c
    m = cpm.best_match(_strip_team(label), list(names))
    return names[m] if m else None


# ── parsing one source ───────────────────────────────────────────────────────

def _empty_source() -> dict:
    return {"mid": {}, "floor": set(), "eliminated": set(), "winner": None, "unmatched": []}


def _no_bid_floor(bid, ask) -> bool:
    b, a = cpm._f(bid), cpm._f(ask)
    return (b is None or b <= 0) and a is not None and 0 < a <= FLOOR_ASK


def parse_kalshi_field(event: dict, mapper, ids: dict) -> dict:
    """Mids / floor runners from a Kalshi field event (one market per runner, label in yes_sub_title)."""
    out = _empty_source()
    for m in (event or {}).get("markets") or []:
        label = str(m.get("yes_sub_title") or m.get("subtitle") or "")
        rid = mapper(label, ids)
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


def parse_poly_field(event: dict, mapper, ids: dict) -> dict:
    """Mids / floor / eliminated runners from a Polymarket field event (one yes/no market per runner)."""
    out = _empty_source()
    for m in (event or {}).get("markets") or []:
        label = str(m.get("groupItemTitle") or "")
        if not label or label.lower() == "other" or re.fullmatch(r"(driver|team|constructor) [a-z]", label.lower()):
            continue                                      # placeholder runners
        rid = mapper(label, ids)
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


def assemble(sources: dict[str, dict], ids: Iterable[str], kind: str, markets: dict | None = None) -> dict:
    """
    Consensus across sources, the thin-market rule, and the de-vig.

    mid_i = mean of source mids for runner i; probs_i = mid_i / sum_j mid_j for quoted
    runners and 0 for floor / eliminated runners.
    """
    ids = list(ids)
    pooled: dict[str, list[float]] = {}
    floor, elim, unmatched, winner = set(), set(), [], None
    for src in sources.values():
        for rid, p in src["mid"].items():
            pooled.setdefault(rid, []).append(p)
        floor |= src["floor"]
        elim |= src["eliminated"]
        unmatched += src["unmatched"]
        winner = winner or src.get("winner")
    mid = {r: sum(ps) / len(ps) for r, ps in pooled.items() if r not in elim}
    floor = (floor - set(mid)) - elim
    total = sum(mid.values())
    accounted = set(mid) | floor | elim
    need = max(4, len(ids) // 2)
    base = {"kind": kind, "markets": markets or {}, "field": len(ids), "quoted": len(mid), "accounted": len(accounted),
            "implied_total": round(total, 4), "overround": round(total - 1.0, 4), "unmatched": sorted(set(unmatched)),
            "sources": {k: {r: round(p, 4) for r, p in v["mid"].items()} for k, v in sources.items()}}
    if winner:
        return {**base, "available": False, "reason": f"settled: {winner} won", "probs": {}, "mid": {}}
    if len(accounted) < need or not (MIN_TOTAL <= total <= MAX_TOTAL) or not mid:
        reason = f"thin: {len(accounted)} of {len(ids)} runners accounted for (need {need}), implied total {total:.2f}"
        logger.info("f1 %s market not published: %s", kind, reason)
        return {**base, "available": False, "reason": reason, "probs": {}, "mid": {k: round(v, 4) for k, v in mid.items()}}
    fair = devig({r: 1.0 / p for r, p in mid.items()})
    probs = {r: round(fair.get(r, 0.0), 5) for r in ids if r in fair}
    for r in floor | elim:
        probs.setdefault(r, 0.0)
    probs = dict(sorted(probs.items(), key=lambda kv: -kv[1]))
    return {**base, "available": True, "reason": None, "probs": probs, "mid": {k: round(v, 4) for k, v in mid.items()},
            "odds": {r: round(1.0 / p, 4) for r, p in mid.items()}, "floor": sorted(floor), "eliminated": sorted(elim)}


# ── public ───────────────────────────────────────────────────────────────────

def _year_suffix(ticker: str) -> str:
    m = re.search(r"-(\d{2})$", str(ticker or ""))
    return m.group(1) if m else ""


def title_prices(kind: str = "drivers", year: int | None = None, store: dict | None = None) -> dict:
    """
    Drivers' or constructors' championship: {"available", "probs": {id: fair p}, "mid", "odds",
    "sources": {"kalshi": {id: mid}, "polymarket": {...}}, "floor", "eliminated", "unmatched",
    "quoted", "accounted", "field", "implied_total", "overround", "markets", "reason"}.
    Never raises; an unreachable or thin market returns available=False.
    """
    kind = "constructors" if str(kind).startswith("con") else "drivers"
    year = year or _season()
    try:
        ids = field(kind, year, store)
        mapper = map_driver if kind == "drivers" else map_constructor
        sources, markets = {}, {}
        events = kalshi_events(KALSHI_SERIES[kind]) or []
        yy = f"{year % 100:02d}"
        ev = next((e for e in events if _year_suffix(e.get("event_ticker")) == yy), events[0] if events else None)
        if ev:
            sources["kalshi"] = parse_kalshi_field(ev, mapper, ids)
            markets["kalshi"] = ev.get("event_ticker")
        for pattern in POLY_TITLE_SLUGS[kind]:
            slug = pattern.format(year=year)
            pev = polymarket_event(slug)
            if pev and not pev.get("closed"):
                sources["polymarket"] = parse_poly_field(pev, mapper, ids)
                markets["polymarket"] = slug
                break
        return assemble(sources, ids, f"title_{kind}", markets)
    except Exception as exc:  # noqa: BLE001
        logger.info("f1 title_prices(%s) failed: %s", kind, exc)
        return {"kind": f"title_{kind}", "available": False, "reason": f"error: {exc}", "probs": {}}


def _date(s) -> datetime | None:
    return cpm._parse_time(s)


def _near(d1, d2, days: int = DATE_WINDOW_DAYS) -> bool:
    return bool(d1 and d2 and abs((d1 - d2).total_seconds()) <= days * 86400)


def _kalshi_event_date(ev: dict) -> datetime | None:
    for m in ev.get("markets") or []:
        d = _date(m.get("occurrence_datetime") or m.get("expected_expiration_time"))
        if d:
            return d
    return None


def _poly_slug_date(slug: str) -> datetime | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})$", str(slug or ""))
    return _date(m.group(1)) if m else None


def race_winner_prices(year: int, rnd: int, store: dict | None = None) -> dict:
    """Race winner market for (year, round), matched by race date (+-3 days); same shape as title_prices."""
    try:
        s = store if store is not None else st.load(year)
        race = (s.get("races") or {}).get(str(rnd)) or {}
        when = _date(race.get("date"))
        ids = field("race", year, s)
        sources, markets = {}, {}
        for ev in kalshi_events(KALSHI_SERIES["race"]) or []:
            if _near(_kalshi_event_date(ev), when):
                sources["kalshi"] = parse_kalshi_field(ev, map_driver, ids)
                markets["kalshi"] = ev.get("event_ticker")
                break
        for ev in polymarket_tag_events(POLY_TAG) or []:
            slug = str(ev.get("slug") or "")
            if "-winner-" in slug and not any(b in slug for b in ("constructor", "sprint", "pole", "practice")) \
                    and _near(_poly_slug_date(slug), when) and not ev.get("closed"):
                sources["polymarket"] = parse_poly_field(ev, map_driver, ids)
                markets["polymarket"] = slug
                break
        out = assemble(sources, ids, "race_winner", markets)
        out.update({"year": year, "round": rnd, "race": race.get("name"), "date": race.get("date")})
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("f1 race_winner_prices(%s, %s) failed: %s", year, rnd, exc)
        return {"kind": "race_winner", "available": False, "reason": f"error: {exc}", "probs": {}}


def _round_for(when: datetime | None, s: dict) -> int | None:
    for rnd, race in (s.get("races") or {}).items():
        if _near(_date(race.get("date")), when):
            return int(rnd)
    return None


_VS = re.compile(r"^(?:.*?:\s*)?(.+?)\s+vs\.?\s+(.+?)\??$", re.I)
_AHEAD = re.compile(r"will (.+?) finish ahead of (.+?) in the", re.I)


def parse_kalshi_h2h(ev: dict, ids: dict) -> dict | None:
    """{a, b, p_a} from a Kalshi KXF1H2H event (one market per driver), or None without a two-sided quote."""
    m = _VS.match(str(ev.get("title") or ""))
    quotes = {}
    for mk in ev.get("markets") or []:
        rid = map_driver(str(mk.get("yes_sub_title") or ""), ids)
        p = cpm.kalshi_price(mk)
        if rid and p is not None:
            quotes[rid] = p
    if m:
        a, b = map_driver(m.group(1), ids), map_driver(m.group(2), ids)
    else:
        a, b = (list(quotes) + [None, None])[:2]
    if not a or not b or a == b:
        return None
    if a in quotes and b in quotes:
        pa = quotes[a] / (quotes[a] + quotes[b])               # de-vig the pair
    elif a in quotes:
        pa = quotes[a]
    elif b in quotes:
        pa = 1.0 - quotes[b]
    else:
        return None
    return {"a": a, "b": b, "p_a": pa}


def parse_poly_h2h(m: dict, ids: dict) -> dict | None:
    """{a, b, p_a} from a Polymarket binary "A vs B" market (price is the first outcome), or None."""
    if m.get("closed"):
        return None
    outs = m.get("outcomes")
    if isinstance(outs, str):
        try:
            import json
            outs = json.loads(outs)
        except ValueError:
            outs = None
    if not outs or len(outs) != 2:
        mm = _VS.match(str(m.get("groupItemTitle") or ""))
        outs = [mm.group(1), mm.group(2)] if mm else None
    if not outs:
        return None
    a, b = map_driver(str(outs[0]), ids), map_driver(str(outs[1]), ids)
    p = cpm.poly_price(m)
    if not a or not b or a == b or p is None:
        return None
    return {"a": a, "b": b, "p_a": p}


def h2h_prices(year: int | None = None, store: dict | None = None) -> dict:
    """
    Open head-to-head markets: {"race": [{"round", "date", "a", "b", "p_a", "p_b", "sources": {src: p_a}}],
    "season": [{"a", "b", "p_a", "p_b", "sources"}], "markets": [...]}. p_a = P(a finishes ahead of b);
    when both sources price a pairing, p_a is their mean. Never raises.
    """
    year = year or _season()
    out: dict[str, Any] = {"race": [], "season": [], "markets": []}
    try:
        s = store if store is not None else st.load(year)
        ids = field("h2h", year, s)
        pooled: dict[tuple, dict] = {}

        def add(scope, rnd, date, rec, src):
            a, b, pa = rec["a"], rec["b"], rec["p_a"]
            if a > b:
                a, b, pa = b, a, 1.0 - pa
            row = pooled.setdefault((scope, rnd, a, b), {"scope": scope, "round": rnd, "date": date, "a": a, "b": b, "sources": {}})
            row["sources"][src] = round(pa, 4)

        for ev in kalshi_events(KALSHI_SERIES["h2h"]) or []:
            rec = parse_kalshi_h2h(ev, ids)
            if rec:
                when = _kalshi_event_date(ev)
                add("race", _round_for(when, s), when.date().isoformat() if when else None, rec, "kalshi")
                out["markets"].append(ev.get("event_ticker"))
        for ev in polymarket_tag_events(POLY_TAG) or []:
            slug = str(ev.get("slug") or "")
            if ev.get("closed"):
                continue
            if "-h2h-" in slug:
                when = _poly_slug_date(slug)
                n = 0
                for m in ev.get("markets") or []:
                    rec = parse_poly_h2h(m, ids)
                    if rec:
                        add("race", _round_for(when, s), when.date().isoformat() if when else None, rec, "polymarket")
                        n += 1
                if n:
                    out["markets"].append(slug)
            elif (mm := _AHEAD.search(str(ev.get("title") or ""))) and "championship" in slug:
                a, b = map_driver(mm.group(1), ids), map_driver(mm.group(2), ids)
                mk = (ev.get("markets") or [{}])[0]
                p = cpm.poly_price(mk)
                if a and b and a != b and p is not None:
                    add("season", None, None, {"a": a, "b": b, "p_a": p}, "polymarket")
                    out["markets"].append(slug)
        for row in pooled.values():
            vals = list(row["sources"].values())
            row["p_a"] = round(sum(vals) / len(vals), 4)
            row["p_b"] = round(1.0 - row["p_a"], 4)
            out[row.pop("scope")].append(row)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("f1 h2h_prices failed: %s", exc)
        return out
