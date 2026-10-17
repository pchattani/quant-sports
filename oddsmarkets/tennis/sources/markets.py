"""
ATP / WTA prices from Kalshi and Polymarket (plus tennis-data closing odds after the fact), mapped to
canonical player ids and store matches.

What exists (surveyed 2026-10-01; Kalshi /series?category=Sports tag "Tennis", Polymarket tag "tennis")

    Kalshi
        KXATPMATCH / KXWTAMATCH   per match, event "KXATPMATCH-26SEP28BUBMEN" ("Bublik vs Mensik"), two markets
                                  whose yes_sub_title is each player's full name                  -> match_prices
        KXATP / KXWTA             tournament winners, one event per tournament: KXATP-26TOKYO, KXATP-26BEIJIN,
                                  KXATP-27AO / -27FO / -27WIM / -27USO (next season's Slams)       -> futures["tournaments"]
        KXATPFINALS / KXWTAFINALS Finals champion (no open event on the survey date)               -> futures["finals_winner"]
        KXATP1RANK / KXWTA1RANK   No. 1 on Dec 31 (KXATP1RANK-26DEC31), a field                    -> futures["year_end_no1"]
        KXATPFINALSQUAL / KXWTAFINALSQUAL  per-player "will qualify" (KXATPFINALSQUAL-26NIT,
                                  KXWTAFINALSQUAL-26RIY); binary, eight qualify                    -> futures["finals_qual"]
        KXATPGRANDSLAM / KXWTAGRANDSLAM  "who will win a Slam in 2027", per player binary          -> futures["slam_next_year"]
        also, not used: set winners, game spreads / totals (KXATPGSPREAD, KXATPGTOTAL), exact score,
        tiebreak, aces, challengers, doubles, exhibitions.
    Polymarket (tag "tennis", paged by 100)
        per match: slug "atp-<a>-<b>-YYYY-MM-DD" / "wta-...", title "<Event>: A vs B", a "moneyline" market
        with outcomes [A, B] (bestBid/bestAsk are A's)                                            -> match_prices
        "ATP 2026 End of Year Rankings: Player to be Number 1" (field)                           -> year_end_no1
        "ATP 2026 End of Year Rankings: Player to Make Top 10" (binary per player)               -> top10
        "Nitto ATP Finals: Player to Qualify" (binary per player)                                -> finals_qual
        "<year> Men's <Slam> Winner (Tennis)" and other "... Winner" fields                      -> tournaments

Prices and the thin-market rule are the basketball / F1 ones: a price is the midpoint of a live two-sided
quote ((bid + ask) / 2, 0 < bid <= ask < 1, ask - bid <= 0.12); sources are averaged per runner; a field is
published only when at least max(4, half the field) runners are accounted for (quoted, written off by a
"no bid / ask <= 2c" quote, or settled No) and the implied total is within 0.8-1.3, then de-vigged
multiplicatively. A match price: Kalshi's two sides de-vigged (q_a / (q_a + q_b)); Polymarket's moneyline
mid is already a two-way price. Binary per-player markets (qualify, top 10) are averaged, not de-vigged
(the implied total is reported: about 8 for the Finals).

Names: market labels are full names ("Alex de Minaur", "Xinyu Wang"); store names can be full or
tennis-data style "De Minaur A.". `map_player` tries, within the match's / event's field first and then
the whole tour: exact folded name or alias, the same tokens in any order, "Surname I." through
canon.abbrev_matches, then surname plus first initial, then one name a token subset of the other with the
same first name ("Tomas Barrios" = "Tomas Barrios Vera"), then a unique surname within the match's field.
Unmatched labels are reported, never guessed; `LAST_STATS` after match_prices gives the name match rate and
splits the misses into players known to the registry but absent from the store (Challengers, qualifying) and
names the registry does not know.
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
MATCH_SERIES = {"atp": "KXATPMATCH", "wta": "KXWTAMATCH"}
TOURN_SERIES = {"atp": "KXATP", "wta": "KXWTA"}
FINALS_SERIES = {"atp": "KXATPFINALS", "wta": "KXWTAFINALS"}
NO1_SERIES = {"atp": "KXATP1RANK", "wta": "KXWTA1RANK"}
QUAL_SERIES = {"atp": "KXATPFINALSQUAL", "wta": "KXWTAFINALSQUAL"}
SLAMYEAR_SERIES = {"atp": "KXATPGRANDSLAM", "wta": "KXWTAGRANDSLAM"}
SLAM_CODES = {"AO": "australian-open", "FO": "roland-garros", "RG": "roland-garros", "WIM": "wimbledon",
              "USO": "us-open"}
SLAM_WORDS = {"australian open": "australian-open", "french open": "roland-garros", "roland garros": "roland-garros",
              "wimbledon": "wimbledon", "us open": "us-open"}
POLY_TAG = "tennis"
DATE_WINDOW = 1

# indirection so tests can swap the network for canned payloads
kalshi_events = cpm.kalshi_events


def poly_tennis_events(closed: bool = False, pages: int = 10) -> list[dict]:
    """All open Polymarket events with the tennis tag (the API pages by 100)."""
    out: list[dict] = []
    for k in range(pages):
        rows = cpm._get(f"{cpm.GAMMA}/events", {"tag_slug": POLY_TAG, "closed": "true" if closed else "false",
                                                "limit": 100, "offset": 100 * k, "order": "endDate", "ascending": "false"})
        if not isinstance(rows, list) or not rows:
            break
        out.extend(rows)
        if len(rows) < 100:
            break
    return out


def _tour(t) -> str:
    return "wta" if str(t or "").lower() == "wta" else "atp"


def _load_store(tour: str, year: int) -> dict:
    try:
        from oddsmarkets.tennis.models import _io
        return _io.load_store(tour, year) or {}
    except Exception:  # noqa: BLE001
        return {}


# ── names ────────────────────────────────────────────────────────────────────

def _fold(s: Any) -> str:
    try:
        from oddsmarkets.tennis import canon
        return canon.fold(s)
    except Exception:  # noqa: BLE001
        return cpm.fold(s)


def _names(rec: dict) -> list[str]:
    out = [rec.get("name"), rec.get("short")] + list(rec.get("aliases") or [])
    return [str(x) for x in out if x]


def _canon():
    try:
        from oddsmarkets.tennis import canon
        return canon
    except Exception:  # noqa: BLE001
        return None


def _parse_abbrev(name: str):
    c = _canon()
    try:
        return c.parse_abbrev(name) if c else None
    except Exception:  # noqa: BLE001
        return None


def _tokens(name: str) -> list[str]:
    c = _canon()
    return c.name_tokens(name) if c else _fold(name).split()


def _abbrev_score(lab_ab, lab_toks, cand_ab, cand_toks) -> int:
    """canon.abbrev_matches between a "Surname I." form and a full name, whichever side is abbreviated."""
    c = _canon()
    if c is None:
        return 0
    try:
        if lab_ab and not cand_ab:
            return c.abbrev_matches(lab_ab[0], lab_ab[1], cand_toks[:1], cand_toks[1:])
        if cand_ab and not lab_ab:
            return c.abbrev_matches(cand_ab[0], cand_ab[1], lab_toks[:1], lab_toks[1:])
    except Exception:  # noqa: BLE001
        return 0
    return 0


def _unique(hits) -> str | None:
    s = sorted(set(hits))
    return s[0] if len(s) == 1 else None


class NameIndex:
    """Folded names, token sets and an inverted token index over a store's players (built once per dict)."""

    def __init__(self, players: dict[str, dict]):
        self.players = players
        self.names: dict[str, list[str]] = {}
        self.parsed: dict[str, list[tuple]] = {}
        self.inv: dict[str, set] = {}
        for pid, rec in players.items():
            raw = [n for n in _names(rec or {}) if n]
            ns = [_fold(n) for n in raw]
            self.names[pid] = [n for n in ns if n]
            self.parsed[pid] = [(_parse_abbrev(n), _tokens(n)) for n in raw]
            for n in self.names[pid]:
                for tok in n.split():
                    if len(tok) >= 2:
                        self.inv.setdefault(tok, set()).add(pid)
        self.n = max(len(players), 1)

    def surnames(self, pid: str) -> set:
        """Last surname token of each of the player's names ("Zverev A." -> zverev, "Alexander Zverev" -> zverev)."""
        out = set()
        for ab, toks in self.parsed.get(pid, []):
            if ab and ab[0]:
                out.add(ab[0][-1])
            elif toks:
                out.add(toks[-1])
        return out

    def candidates(self, ltoks: list[str], cap: int = 40) -> set:
        """Players sharing a token with the label, the rarest shared tokens first (at most `cap`)."""
        score: dict = {}
        for tok in set(ltoks):
            if len(tok) < 2:
                continue
            hits = self.inv.get(tok, set())
            if not hits:
                continue
            w = math.log(self.n / len(hits)) + 1e-3
            for p in hits:
                score[p] = score.get(p, 0.0) + w
        if len(score) <= cap:
            return set(score)
        return set(sorted(score, key=lambda p: -score[p])[:cap])

    def lookup(self, label: str, field: Iterable[str] | None = None) -> str | None:
        key = _fold(label)
        ltoks = key.split()
        if not ltoks:
            return None
        cand = self.candidates(ltoks)
        lab_ab, lab_toks = _parse_abbrev(label), _tokens(label)
        fs = set(field or ()) & set(self.players)
        pools = ([cand & fs] if fs else []) + [cand]
        for k, pool in enumerate(pools):
            if not pool:
                continue
            in_field = bool(fs) and k == 0
            hit = _unique([p for p in pool if key in self.names[p]])
            if hit:
                return hit
            st = sorted(ltoks)
            hit = _unique([p for p in pool if any(sorted(n.split()) == st for n in self.names[p])])
            if hit:
                return hit
            sc = {}
            for p in pool:
                best = max((_abbrev_score(lab_ab, lab_toks, ab, toks) for ab, toks in self.parsed[p]), default=0)
                if best:
                    sc[p] = best
            if sc:
                top = max(sc.values())
                hit = _unique([p for p, v in sc.items() if v == top])
                if hit:
                    return hit
            cands = []
            for p in pool:
                for n in self.names[p]:
                    nt = n.split()
                    if len(nt) >= 2 and len(ltoks) >= 2 and nt[-1] == ltoks[-1] and nt[0][:1] == ltoks[0][:1]:
                        cands.append(p)
                    elif len(nt) >= 2 and len(ltoks) >= 2 and set(nt) <= set(ltoks) | {ltoks[0][:1]}:
                        cands.append(p)
            hit = _unique(cands)
            if hit:
                return hit
            # one name a token subset of the other, same first name, two or more shared tokens:
            # "Tomas Barrios" = "Tomas Barrios Vera", "Mateus Cardoso Alves" = "Mateus De Carvalho Cardoso Alves"
            sub = []
            ls = set(ltoks)
            for p in pool:
                for n in self.names[p]:
                    nt = n.split()
                    ns = set(nt)
                    if len(ns & ls) >= 2 and nt[0] == ltoks[0] and (ns <= ls or ls <= ns):
                        sub.append(p)
            hit = _unique(sub)
            if hit:
                return hit
            # a bare surname: the unique last token, inside the field or for a one-word label
            if in_field or len(ltoks) == 1:
                last = ltoks[-1]
                hit = _unique([p for p in pool if last in self.surnames(p)])
                if hit:
                    return hit
        return None


_IDX: dict = {}


def name_index(players: dict[str, dict]) -> NameIndex:
    key = (id(players), len(players))
    ix = _IDX.get(key)
    if ix is None or ix.players is not players:
        if len(_IDX) > 8:
            _IDX.clear()
        ix = _IDX[key] = NameIndex(players)
    return ix


def map_player(label: str | None, players: dict[str, dict], field: Iterable[str] | None = None) -> str | None:
    """Canonical pid for a market label, or None when unsure. `field` (pids) is searched first."""
    if not label or not players:
        return None
    return name_index(players).lookup(str(label), field)


# ── field markets (the basketball template) ─────────────────────────────────

def _empty_source() -> dict:
    return {"mid": {}, "floor": set(), "eliminated": set(), "winner": None, "unmatched": []}


def _no_bid_floor(bid, ask) -> bool:
    b, a = cpm._f(bid), cpm._f(ask)
    return (b is None or b <= 0) and a is not None and 0 < a <= FLOOR_ASK


CEIL_BID = 0.9


def _ceiling(bid, ask) -> float | None:
    """A near-certain yes quoted "bid >= 0.90, ask 1.00" (no seller below 1): the price is (bid + 1) / 2. Binary
    per-player markets only (the mirror of the field markets' no-bid floor)."""
    b, a = cpm._f(bid), cpm._f(ask)
    if b is not None and a is not None and b >= CEIL_BID and a >= 0.999 and a - b <= cpm.MAX_SPREAD:
        return (b + 1.0) / 2.0
    return None


def _skip_label(label: str) -> bool:
    """Placeholders ("A", "B", "Other") and doubles pairs ("Arends/Pel")."""
    f = _fold(label)
    return len(f) <= 1 or "/" in str(label) or f in ("other", "another player", "field", "any other player")


def parse_kalshi_field(event: dict, mapper) -> dict:
    out = _empty_source()
    for m in (event or {}).get("markets") or []:
        label = str(m.get("yes_sub_title") or m.get("subtitle") or "")
        if _skip_label(label):
            continue
        rid = mapper(label)
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
    out = _empty_source()
    for m in (event or {}).get("markets") or []:
        label = str(m.get("groupItemTitle") or "")
        if not label or _skip_label(label):
            continue
        rid = mapper(label)
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
    """TITLE: {"available","reason","probs","mid","odds","sources","by_source","floor","eliminated","unmatched",
    "field","quoted","accounted","implied_total","overround","markets","kind"}."""
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


def binary(sources: dict[str, dict], kind: str, markets: dict | None = None) -> dict:
    """Per-player yes/no markets: {"available","probs": {pid: mean mid (settled 1/0)},"by_source","implied_total",...}."""
    pooled: dict[str, list[float]] = {}
    unmatched: list = []
    for v in sources.values():
        for p, x in v["mid"].items():
            pooled.setdefault(p, []).append(x)
        for p in v["eliminated"]:
            pooled.setdefault(p, []).append(0.0)
        if v.get("winner"):
            pooled.setdefault(v["winner"], []).append(1.0)
        for p in v.get("yes", set()):
            pooled.setdefault(p, []).append(1.0)
        unmatched += v["unmatched"]
    probs = {p: round(sum(x) / len(x), 4) for p, x in pooled.items()}
    probs = dict(sorted(probs.items(), key=lambda kv: -kv[1]))
    ceil = sorted({p for v in sources.values() for p in v.get("ceiling", set())})
    return {"kind": kind, "available": bool(probs), "probs": probs, "markets": markets or {},
            "implied_total": round(sum(probs.values()), 3), "ceiling": ceil,
            "by_source": {k: {p: round(x, 4) for p, x in v["mid"].items()} for k, v in sources.items()},
            "unmatched": sorted(set(unmatched))}


def parse_kalshi_binary(event: dict, mapper) -> dict:
    """Per-player binary markets in one Kalshi event (each market its own yes/no)."""
    out = _empty_source()
    out["yes"] = set()
    for m in (event or {}).get("markets") or []:
        label = str(m.get("yes_sub_title") or "")
        if _skip_label(label):
            continue
        rid = mapper(label)
        if not rid:
            if label:
                out["unmatched"].append(label)
            continue
        res = str(m.get("result") or "").lower()
        if res == "no":
            out["eliminated"].add(rid)
        elif res == "yes":
            out["yes"].add(rid)
        else:
            p = cpm.kalshi_price(m)
            if p is None:
                p = _ceiling(m.get("yes_bid_dollars"), m.get("yes_ask_dollars"))
                if p is not None:
                    out.setdefault("ceiling", set()).add(rid)
            if p is not None:
                out["mid"][rid] = p
    return out


def parse_poly_binary(event: dict, mapper) -> dict:
    out = _empty_source()
    out["yes"] = set()
    for m in (event or {}).get("markets") or []:
        label = str(m.get("groupItemTitle") or "")
        if not label or _skip_label(label):
            continue
        rid = mapper(label)
        if not rid:
            out["unmatched"].append(label)
            continue
        s = cpm.poly_resolved(m)
        if s == 0.0:
            out["eliminated"].add(rid)
        elif s == 1.0:
            out["yes"].add(rid)
        elif not m.get("closed"):
            p = cpm.poly_price(m)
            if p is None:
                p = _ceiling(m.get("bestBid"), m.get("bestAsk"))
                if p is not None:
                    out.setdefault("ceiling", set()).add(rid)
            if p is not None:
                out["mid"][rid] = p
    return out


# ── tournaments ──────────────────────────────────────────────────────────────

def _event_for(label: str, year: int, tour: str, stores: dict[int, dict], code: str | None = None) -> str | None:
    """Store event id for a market's tournament ("2026 ATP Tokyo", code "TOKYO" / "AO")."""
    if code and code.upper() in SLAM_CODES:
        return f"{SLAM_CODES[code.upper()]}-{year}"
    f = _fold(label)
    for w, tid in SLAM_WORDS.items():
        if w in f:
            return f"{tid}-{year}"
    st = stores.get(year) or {}
    words = [w for w in f.split() if w not in ("atp", "wta", "men", "mens", "women", "womens", "s", "winner", "singles",
                                                 "tennis", "open", "championships", "tournament", str(year))]
    best = []
    for eid, ev in (st.get("events") or {}).items():
        if str(ev.get("level")) in ("ch", "q"):
            continue
        hay = " ".join(_fold(x) for x in (ev.get("name"), ev.get("city"), ev.get("tid")) if x)
        hw = hay.split()
        if code and any(h.startswith(_fold(code)) for h in hw if len(_fold(code)) >= 4):
            best.append(eid)
            continue
        if words and all(any(h.startswith(w) or w.startswith(h) for h in hw if len(h) >= 3) for w in words):
            best.append(eid)
    return best[0] if len(set(best)) == 1 else None


def _kalshi_code(event_ticker: str) -> tuple[int | None, str | None]:
    m = re.search(r"-(\d{2})([A-Z0-9]+)$", str(event_ticker or ""))
    if not m:
        return None, None
    return 2000 + int(m.group(1)), m.group(2)


def _title_tour(title: str) -> str | None:
    t = _fold(title)
    if re.search(r"\bwta\b|\bwomen|\bwomens\b|\bladies\b", t):
        return "wta"
    if re.search(r"\batp\b|\bmen\b|\bmens\b|nitto", t):
        return "atp"
    return None


def futures(tour: str, year: int | None = None, stores: dict[int, dict] | None = None,
            poly_events: list[dict] | None = None) -> dict:
    """
    {"tour","generated_at","tournaments": {key: TITLE + {"event","label"}},"finals_winner": TITLE | None,
     "year_end_no1": TITLE,"finals_qual": BINARY,"top10": BINARY,"slam_next_year": BINARY}. Never raises.
    """
    t = _tour(tour)
    out: dict[str, Any] = {"tour": t, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        Y = int(year or datetime.now(timezone.utc).year)
        stores = stores if stores is not None else {y: _load_store(t, y) for y in (Y, Y + 1)}
        players: dict = {}
        for s in stores.values():
            players.update((s or {}).get("players") or {})
        pev = poly_events if poly_events is not None else poly_tennis_events()
        pev = [e for e in pev if not e.get("closed")]

        def mapper_for(field=None):
            return lambda label: map_player(label, players, field)
        # tournaments
        tours = {}
        for ev in kalshi_events(TOURN_SERIES[t]) or []:
            yr, code = _kalshi_code(ev.get("event_ticker"))
            label = str(ev.get("sub_title") or ev.get("title") or "")
            eid = _event_for(label, yr or Y, t, stores, code) if yr else None
            sevt = ((stores.get(yr) or {}).get("events") or {}).get(eid) if eid else None
            field = [s[1] for s in ((sevt or {}).get("draw") or {}).get("slots") or [] if s[1]] or None
            src = {"kalshi": parse_kalshi_field(ev, mapper_for(field))}
            key = eid or ev.get("event_ticker")
            tours[key] = {"src": src, "markets": {"kalshi": ev.get("event_ticker")}, "event": eid, "label": label, "field": field}
        for ev in pev:
            title = str(ev.get("title") or "")
            if not re.search(r"\bwinner\b", title, re.I) or " vs " in title or "doubles" in title.lower():
                continue
            if _title_tour(title) != t:
                continue
            ym = re.search(r"\b(20\d\d)\b", title)
            yr = int(ym.group(1)) if ym else Y
            eid = _event_for(title, yr, t, stores)
            key = eid or ev.get("slug")
            sevt = ((stores.get(yr) or {}).get("events") or {}).get(eid) if eid else None
            field = [s[1] for s in ((sevt or {}).get("draw") or {}).get("slots") or [] if s[1]] or None
            rec = tours.setdefault(key, {"src": {}, "markets": {}, "event": eid, "label": title, "field": field})
            rec["src"]["polymarket"] = parse_poly_field(ev, mapper_for(field))
            rec["markets"]["polymarket"] = ev.get("slug")
        out["tournaments"] = {k: {**assemble(v["src"], v["field"], "tournament", v["markets"]), "event": v["event"],
                                  "label": v["label"]} for k, v in tours.items()}
        # Finals champion
        fin = [e for e in (kalshi_events(FINALS_SERIES[t]) or [])]
        out["finals_winner"] = assemble({"kalshi": parse_kalshi_field(fin[0], mapper_for())}, None, "finals_winner",
                                        {"kalshi": fin[0].get("event_ticker")}) if fin else None
        # year-end No. 1
        src, mk = {}, {}
        no1 = kalshi_events(NO1_SERIES[t]) or []
        if no1:
            src["kalshi"] = parse_kalshi_field(no1[0], mapper_for())
            mk["kalshi"] = no1[0].get("event_ticker")
        for ev in pev:
            title = str(ev.get("title") or "")
            if _title_tour(title) == t and re.search(r"number 1|no\.? ?1\b|#1", title, re.I) and "rank" in title.lower():
                src["polymarket"] = parse_poly_field(ev, mapper_for())
                mk["polymarket"] = ev.get("slug")
                break
        out["year_end_no1"] = assemble(src, None, "year_end_no1", mk) if src else {"kind": "year_end_no1", "available": False,
                                                                                    "reason": "no market", "probs": {}}
        # Finals qualification, top 10, Slam next year (binary)
        src, mk = {}, {}
        q = kalshi_events(QUAL_SERIES[t]) or []
        if q:
            src["kalshi"] = parse_kalshi_binary(q[0], mapper_for())
            mk["kalshi"] = q[0].get("event_ticker")
        for ev in pev:
            title = str(ev.get("title") or "")
            if _title_tour(title) == t and re.search(r"finals.*qualif", title, re.I):
                src["polymarket"] = parse_poly_binary(ev, mapper_for())
                mk["polymarket"] = ev.get("slug")
                break
        out["finals_qual"] = binary(src, "finals_qual", mk)
        src, mk = {}, {}
        for ev in pev:
            title = str(ev.get("title") or "")
            if _title_tour(title) == t and re.search(r"top 10", title, re.I):
                src["polymarket"] = parse_poly_binary(ev, mapper_for())
                mk["polymarket"] = ev.get("slug")
                break
        out["top10"] = binary(src, "top10", mk)
        gs = kalshi_events(SLAMYEAR_SERIES[t]) or []
        out["slam_next_year"] = binary({"kalshi": parse_kalshi_binary(gs[0], mapper_for())}, "slam_next_year",
                                       {"kalshi": gs[0].get("event_ticker")}) if gs else None
    except Exception as exc:  # noqa: BLE001
        logger.info("tennis futures(%s) failed: %s", t, exc)
        out["error"] = str(exc)
    return out


# ── per match ────────────────────────────────────────────────────────────────

_MON = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def kalshi_match_date(ticker: str) -> date | None:
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", str(ticker or ""))
    if not m or m.group(2) not in _MON:
        return None
    try:
        return date(2000 + int(m.group(1)), _MON[m.group(2)], int(m.group(3)))
    except ValueError:
        return None


def _day(x) -> date | None:
    try:
        return date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def _book_p1(odds: dict | None, key: str) -> float | None:
    o = (odds or {}).get(key)
    try:
        a, b = float(o[0]), float(o[1])
    except (TypeError, ValueError, IndexError):
        return None
    if a <= 1.0 or b <= 1.0:
        return None
    f = devig({"1": a, "2": b})
    return round(float(f["1"]), 5) if f else None


def _outcomes(m: dict) -> list | None:
    o = m.get("outcomes")
    if isinstance(o, str):
        try:
            o = json.loads(o)
        except ValueError:
            return None
    return o if isinstance(o, list) else None


LAST_STATS: dict = {}


def _registry_players(tour: str) -> dict:
    """{pid: player} from docs/ace/data/<tour>/registry.json (every player canon knows), {} when absent."""
    try:
        from oddsmarkets.tennis.models import _io
        r = _io.read_json(_io.data_root() / _tour(tour) / "registry.json") or {}
        return r.get("players") or {}
    except Exception:  # noqa: BLE001
        return {}


def match_prices(tour: str, d: Any = None, store: dict | None = None, poly_events: list[dict] | None = None,
                 window: int = DATE_WINDOW, registry: dict | None = None) -> dict[str, dict]:
    """
    {mid: {"p1": P(store p1 wins) | None,"sources": [{"source","p1","market"}],"bookmakers": {"ps","avg","b365","max"},
           "p1_pid","p2_pid","basis"}} for the store's matches within `window` days of `d`.
    p1 = the mean of the prediction-market sources; without them, Pinnacle's de-vigged closing price, else the
    average odds. Never raises.
    """
    t = _tour(tour)
    try:
        dd = d if isinstance(d, date) else (_day(d) or datetime.now(timezone.utc).date())
        s = store if store is not None else _load_store(t, dd.year)
        players = s.get("players") or {}
        cands = [m for m in (s.get("matches") or {}).values()
                 if isinstance(m, dict) and _day(m.get("date")) and abs((_day(m["date"]) - dd).days) <= window
                 and str(m.get("round") or "") not in ("Q1", "Q2", "Q3")]
        field = sorted({str(m.get(k)) for m in cands for k in ("p1", "p2") if m.get(k)})
        bypair: dict = {}
        for m in cands:
            bypair.setdefault(frozenset((str(m["p1"]), str(m["p2"]))), []).append(m)

        def find(a, b, when):
            hits = bypair.get(frozenset((a, b))) or []
            if when and len(hits) > 1:
                hits = sorted(hits, key=lambda m: abs((_day(m["date"]) - when).days))
            return hits[0] if hits else None
        out: dict[str, dict] = {}
        unmatched: list = []

        def rec(m):
            mid = str(m.get("id"))
            if mid not in out:
                bk = {k: _book_p1(m.get("odds"), k) for k in ("ps", "avg", "b365", "max")}
                out[mid] = {"p1_pid": str(m["p1"]), "p2_pid": str(m["p2"]), "sources": [],
                            "bookmakers": {k: v for k, v in bk.items() if v is not None}, "p1": None, "basis": None}
            return out[mid]

        stats = {"events": 0, "names": 0, "names_mapped": 0, "matched_to_store": 0}
        for ev in kalshi_events(MATCH_SERIES[t]) or []:
            ed = kalshi_match_date(ev.get("event_ticker"))
            if ed and abs((ed - dd).days) > window + 1:
                continue
            stats["events"] += 1
            q, ids = {}, []
            for mk in ev.get("markets") or []:
                stats["names"] += 1
                pid = map_player(mk.get("yes_sub_title"), players, field)
                if not pid:
                    unmatched.append(str(mk.get("yes_sub_title")))
                    continue
                stats["names_mapped"] += 1
                ids.append(pid)
                p = cpm.kalshi_price(mk)
                if p is not None:
                    q[pid] = p
            if len(ids) != 2 or not q:
                continue
            m = find(ids[0], ids[1], ed)
            if not m:
                continue
            stats["matched_to_store"] += 1
            a, b = str(m["p1"]), str(m["p2"])
            if a in q and b in q:
                p1 = q[a] / (q[a] + q[b])
            elif a in q:
                p1 = q[a]
            else:
                p1 = 1.0 - q[b]
            rec(m)["sources"].append({"source": "kalshi", "p1": round(p1, 4), "market": ev.get("event_ticker")})
        pevs = poly_events if poly_events is not None else poly_tennis_events()
        for ev in pevs:
            slug = str(ev.get("slug") or "")
            mm = re.fullmatch(rf"{t}-[a-z0-9-]+-(\d{{4}}-\d{{2}}-\d{{2}})", slug)
            if not mm or ev.get("closed"):
                continue
            ed = _day(mm.group(1))
            if ed and abs((ed - dd).days) > window + 1:
                continue
            ml = next((x for x in ev.get("markets") or [] if x.get("sportsMarketType") == "moneyline"), None)
            outs = _outcomes(ml) if ml else None
            if not ml or not outs or len(outs) != 2:
                continue
            if any("/" in str(x) for x in outs):
                continue                                         # doubles
            stats["events"] += 1
            stats["names"] += 2
            pa, pb = map_player(outs[0], players, field), map_player(outs[1], players, field)
            stats["names_mapped"] += bool(pa) + bool(pb)
            if not pa or not pb:
                unmatched += [str(x) for x, p in ((outs[0], pa), (outs[1], pb)) if not p]
                continue
            m = find(pa, pb, ed)
            price = cpm.poly_price(ml)
            if not m or price is None:
                continue
            stats["matched_to_store"] += 1
            p1 = price if str(m["p1"]) == pa else 1.0 - price
            rec(m)["sources"].append({"source": "polymarket", "p1": round(p1, 4), "market": slug})
        for m in cands:
            if m.get("odds"):
                rec(m)
        for mid, r in out.items():
            pm = [x["p1"] for x in r["sources"]]
            if pm:
                r["p1"], r["basis"] = round(sum(pm) / len(pm), 4), "prediction_markets"
            elif "ps" in r["bookmakers"]:
                r["p1"], r["basis"] = r["bookmakers"]["ps"], "pinnacle_close"
            elif "avg" in r["bookmakers"]:
                r["p1"], r["basis"] = r["bookmakers"]["avg"], "avg_close"
        # unmatched labels: a known player with no match in the store (Challengers, qualifying) or a name failure
        reg = registry if registry is not None else _registry_players(t)
        absent, failed = [], []
        for lab in sorted(set(unmatched)):
            (absent if (reg and map_player(lab, reg)) else failed).append(lab)
        stats.update({"name_rate": round(stats["names_mapped"] / stats["names"], 4) if stats["names"] else None,
                      "unmatched_known_elsewhere": absent, "unmatched_unknown": failed,
                      "name_rate_excluding_absent": round((stats["names_mapped"] + sum(unmatched.count(a) for a in absent))
                                                          / stats["names"], 4) if stats["names"] else None})
        LAST_STATS.clear()
        LAST_STATS.update({"tour": t, "date": dd.isoformat(), **stats})
        if failed:
            logger.info("tennis match_prices(%s): names not in the registry %s", t, failed[:20])
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("tennis match_prices(%s) failed: %s", t, exc)
        return {}
