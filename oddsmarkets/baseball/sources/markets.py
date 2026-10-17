"""
MLB prices from Kalshi and Polymarket (and the DraftKings lines ESPN carries in the store), mapped to MLBAM
team ids and player ids.

What exists (surveyed 2026-10-01; Kalshi /events?series_ticker=..., Polymarket tag "mlb")

    Kalshi (one event per season; event ticker suffix = the season's two-digit year)
        KXMLB-26            World Series champion, 30 markets, ticker suffix = team code (KXMLB-26-NYY)
        KXMLBAL-26 / KXMLBNL-26        pennants (15 markets each)
        KXMLBALMVP-26, KXMLBNLMVP-26, KXMLBALCY-26, KXMLBNLCY-26, KXMLBALROTY-26, KXMLBNLROTY-26   awards
                            (markets labelled by player name, ticker suffix = initial + four letters)
        KXMLBSERIES-26PHIATLWC          series winner (suffix WC / ALDS / NLDS / ALCS / NLCS / WS), one market per team
        KXMLBGAME-26OCT011400PHIATL     game winner (away code then home code), one market per team
        KXMLBTOTAL-26OCT011400PHIATL    "Over X runs scored" ladder (floor_strike X)
        KXMLBSPREAD-26OCT011400PHIATL   "<team> wins by over X runs" (ticker suffix code + X rounded up)
    Polymarket (tag "mlb")
        "MLB World Series Champion 2026", "MLB: 2026 American League Champion" / "National League Champion",
        "MLB: 2026 AL MVP", "MLB: 2026 NL Cy Young Winner", "MLB: AL Rookie of the Year" (no year in the
        title: the season comes from the end date), "MLB Playoffs: Team to advance to NLDS / ALCS / NLCS"
        (per-team yes/no), "MLB Playoffs: Who Will Win Series? - Braves vs. Phillies" (one market, outcomes
        the two nicknames), per game "mlb-<away>-<home>-YYYY-MM-DD" (sportsMarketType moneyline, spreads with
        `line`, totals with `line`, nrfi, baseball_team_first_five_spread / _total) and
        "...-first-five-winner" (per team yes/no plus "Draw").

Prices and the thin-market rule are Hardwood's (basketball/sources/markets.py): a price is the midpoint of a
live two-sided quote ((bid + ask) / 2, 0 < bid <= ask < 1, ask - bid <= 0.12); sources are averaged per
runner; a field market is published only when at least max(4, half the field) runners are accounted for
(quoted, written off by a "no bid / ask <= 2c" quote, or settled No) and the implied total is within 0.8-1.3,
then de-vigged multiplicatively. For award markets the field is the runners the markets list.
Two-way markets (series, games) are de-vigged across their two sides: p_A = mid_A / (mid_A + mid_B) when both
are quoted, else the one quoted side.

Names: teams by the market's team code (alias table to MLBAM abbreviations), else `best_match` over the
store's full name, nickname and location ("Chicago WS", "New York Y", "Los Angeles D" are resolved by
code); players by the store's (or the people crosswalk's) names.
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
    map_player,
    parse_kalshi_field,
    parse_poly_field,
)
from oddsmarkets.common import prediction_markets as cpm
from oddsmarkets.common.markets import devig
from oddsmarkets.common.edge import devig as _dv

logger = logging.getLogger(__name__)

POLY_TAG = "mlb"
CODE_ALIASES = {"ARI": "AZ", "OAK": "ATH", "CHW": "CWS", "KCR": "KC", "SDP": "SD", "SFG": "SF", "TBR": "TB",
                "WSN": "WSH", "WAS": "WSH", "LA": "LAD", "ANA": "LAA", "FLA": "MIA", "TBD": "TB", "NYA": "NYY",
                "NYN": "NYM", "CHA": "CWS", "CHN": "CHC", "SLN": "STL", "SFN": "SF", "SDN": "SD", "KCA": "KC",
                "LAN": "LAD", "TBA": "TB", "AS": "ATH"}
TITLE_KINDS = {
    "champion": ("KXMLB", r"World Series Champion"),
    "AL": ("KXMLBAL", r"American League Champion"),
    "NL": ("KXMLBNL", r"National League Champion"),
}
AWARD_KINDS = {
    "al_mvp": ("KXMLBALMVP", r"\bAL MVP\b|American League MVP"),
    "nl_mvp": ("KXMLBNLMVP", r"\bNL MVP\b|National League MVP"),
    "al_cy": ("KXMLBALCY", r"\bAL Cy Young"),
    "nl_cy": ("KXMLBNLCY", r"\bNL Cy Young"),
    "al_roy": ("KXMLBALROTY", r"\bAL Rookie of the Year"),
    "nl_roy": ("KXMLBNLROTY", r"\bNL Rookie of the Year"),
}
ADVANCE_KINDS = {"ALDS": r"advance to (the )?ALDS", "NLDS": r"advance to (the )?NLDS", "ALCS": r"advance to (the )?ALCS",
                 "NLCS": r"advance to (the )?NLCS", "WS": r"advance to (the )?World Series"}
SERIES_ROUND = {"WC": "WC", "ALWC": "WC", "NLWC": "WC", "ALDS": "DS", "NLDS": "DS", "ALCS": "CS", "NLCS": "CS", "WS": "WS"}

# indirection so tests can swap the network for canned payloads
kalshi_events = cpm.kalshi_events
polymarket_tag_events = cpm.polymarket_tag_events


def _load_store(season: int) -> dict:
    try:
        from oddsmarkets.baseball.models import _dio
        return _dio.load_store("mlb", season)
    except Exception:  # noqa: BLE001
        return {}


def season_for(d: date | None = None) -> int:
    d = d or datetime.now(timezone.utc).date()
    return d.year


# ── names ────────────────────────────────────────────────────────────────────

def _nick(info: dict) -> str:
    if info.get("short"):
        return str(info["short"])
    name = str(info.get("name") or "")
    for two in ("Red Sox", "White Sox", "Blue Jays"):
        if name.endswith(two):
            return two
    return name.split()[-1] if name else ""


def _location(info: dict) -> str:
    name, nick = str(info.get("name") or ""), _nick(info)
    if nick and name.endswith(nick):
        return name[: -len(nick)].strip()
    return str(info.get("location") or "")


def map_team(label: str | None, teams: dict[str, dict], code: str | None = None) -> str | None:
    """MLBAM team id for a market's team code / label, or None when unsure."""
    if not teams:
        return None
    if code:
        c = str(code).upper()
        c = CODE_ALIASES.get(c, c)
        hit = [t for t, v in teams.items() if str((v or {}).get("abbr") or "").upper() in (c, CODE_ALIASES.get(str((v or {}).get("abbr") or "").upper(), "~"))]
        if len(hit) == 1:
            return hit[0]
    if not label:
        return None
    lab = str(label).strip()
    fl = cpm.fold(lab)
    if fl in ("a s", "as", "athletics", "a's"):
        hit = [t for t, v in teams.items() if "athletics" in cpm.fold(v.get("name") or "")]
        if len(hit) == 1:
            return hit[0]
    # "Chicago WS" / "Chicago C" / "New York Y" / "Los Angeles D": location plus a nickname prefix
    m = re.fullmatch(r"(.+?)\s+([A-Za-z]{1,2})", lab)
    if m:
        loc, ini = cpm.fold(m.group(1)), m.group(2).lower()
        def _ini_ok(v):
            nk = cpm.fold(_nick(v))
            initials = "".join(w[0] for w in nk.split() if w)
            return initials.startswith(ini) if len(ini) > 1 else nk.replace(" ", "").startswith(ini)
        hit = [t for t, v in teams.items() if cpm.fold(_location(v)) == loc and _ini_ok(v)]
        if len(hit) == 1:
            return hit[0]
    names = {}
    for t, v in teams.items():
        for x in (v.get("name"), _nick(v), _location(v), v.get("abbr")):
            if x:
                names.setdefault(cpm.fold(str(x)), set()).add(t)
    if fl in names and len(names[fl]) == 1:
        return next(iter(names[fl]))
    nick = [t for t, v in teams.items() if (n := cpm.fold(_nick(v))) and (" " + fl).endswith(" " + n)]
    if len(nick) == 1:
        return nick[0]
    cand = {}
    for t, v in teams.items():
        for x in (v.get("name"), _nick(v), _location(v)):
            if x:
                cand.setdefault(str(x), set()).add(t)
    cand = {k: next(iter(v)) for k, v in cand.items() if len(v) == 1}
    best = cpm.best_match(lab, list(cand))
    return cand[best] if best else None


def _real(teams: dict) -> dict:
    """Drop bracket placeholders ("ATL/PHI", "NL Higher Seed") the store carries for unset postseason games."""
    return {t: v for t, v in teams.items() if not (v or {}).get("placeholder")}


def _ticker_code(ticker: str | None) -> str | None:
    t = str(ticker or "")
    return t.rsplit("-", 1)[-1] if "-" in t else None


def _players(store: dict) -> dict:
    pl = dict(store.get("players") or {})
    if len(pl) < 500:
        try:
            from oddsmarkets.baseball.models import _dio
            for pid, v in (_dio.people() or {}).items():
                if pid not in pl and (v or {}).get("name") and str((v or {}).get("last") or "9999")[:4] >= "2024":
                    pl[pid] = {"name": v["name"]}
        except Exception:  # noqa: BLE001
            pass
    return pl


# ── event selection ──────────────────────────────────────────────────────────

def _yy(season: int) -> str:
    return f"{int(season) % 100:02d}"


def _kalshi_event(series: str, season: int, events: dict | None = None) -> dict | None:
    evs = (events or {}).get(series) if events is not None else kalshi_events(series)
    for e in evs or []:
        if re.search(rf"-{_yy(season)}$", str(e.get("event_ticker") or "")):
            return e
    return None


def _poly_season_ok(ev: dict, season: int) -> bool:
    title = str(ev.get("title") or "")
    if str(season) in title:
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


def _poly_events(poly_events: list[dict] | None) -> list[dict]:
    return poly_events if poly_events is not None else (polymarket_tag_events(POLY_TAG) or [])


# ── futures ──────────────────────────────────────────────────────────────────

def title_prices(season: int, kind: str, store: dict | None = None, poly_events: list[dict] | None = None,
                 kalshi: dict | None = None) -> dict:
    """champion / AL / NL pennant, or an award (al_mvp ... nl_roy) as a TITLE dict. Never raises."""
    try:
        s = store if store is not None else _load_store(season)
        teams = _real(s.get("teams") or {})
        if kind in AWARD_KINDS:
            spec = AWARD_KINDS[kind]
            players = _players(s)

            def mapper(label, code):
                lab = str(label or "").strip()
                if not lab or re.fullmatch(r"(player [a-z]{1,2}|other|field|tie.*|.*co-winners.*)", lab.lower()):
                    return None
                # an unmatched name keeps an accent-folded id so Kalshi's "Yordan Álvarez" and Polymarket's
                # "Yordan Alvarez" pool together
                return map_player(lab, players) or f"name:{cpm.fold(lab)}"
            ids = None
        else:
            spec = TITLE_KINDS[kind]

            def mapper(label, code):
                return map_team(label, teams, code)
            ids = [t for t, v in teams.items() if kind == "champion" or str(v.get("league") or "") == kind] or list(teams)
        sources, markets = {}, {}
        ev = _kalshi_event(spec[0], season, kalshi)
        if ev:
            sources["kalshi"] = parse_kalshi_field(ev, mapper)
            markets["kalshi"] = ev.get("event_ticker")
        pev = _poly_find(_poly_events(poly_events), spec[1], season, exclude=r"Manager|Comeback|Gold Glove|Hank Aaron")
        if pev:
            sources["polymarket"] = parse_poly_field(pev, mapper)
            markets["polymarket"] = pev.get("slug")
        if not teams and kind not in AWARD_KINDS:
            ids = None
        return assemble(sources, ids, kind, markets)
    except Exception as exc:  # noqa: BLE001
        logger.info("mlb title_prices(%s) failed: %s", kind, exc)
        return {"kind": kind, "available": False, "reason": f"error: {exc}", "probs": {}}


def advance_prices(season: int, store: dict | None = None, poly_events: list[dict] | None = None) -> dict:
    """{"NLDS": {tid: p}, "ALCS": ..., ...} from Polymarket's per-team "advance to" markets (mids; settled 0/1)."""
    s = store if store is not None else _load_store(season)
    teams = _real(s.get("teams") or {})
    out = {}
    for rnd, pat in ADVANCE_KINDS.items():
        ev = _poly_find(_poly_events(poly_events), pat, season)
        if not ev:
            continue
        src = parse_poly_field(ev, lambda label, code: map_team(label, teams, code))
        probs = {t: round(p, 4) for t, p in src["mid"].items()}
        for t in src["eliminated"]:
            probs[t] = 0.0
        if src.get("winner"):
            probs[src["winner"]] = 1.0
        out[rnd] = {"probs": probs, "market": ev.get("slug"), "floor": sorted(src["floor"]),
                    "unmatched": src["unmatched"]}
    return out


def _two_way(qa: float | None, qb: float | None) -> float | None:
    """P(A) from the two sides' mids (normalised when both are quoted)."""
    if qa is not None and qb is not None and qa + qb > 0:
        return qa / (qa + qb)
    if qa is not None:
        return qa
    if qb is not None:
        return 1.0 - qb
    return None


def series_prices(season: int, store: dict | None = None, poly_events: list[dict] | None = None,
                  kalshi: dict | None = None) -> list[dict]:
    """[{"teams": [a, b], "round", "probs": {a: p, b: 1 - p}, "sources": [{"source","p","market"}]}]"""
    s = store if store is not None else _load_store(season)
    teams = _real(s.get("teams") or {})
    found: dict = {}
    evs = (kalshi or {}).get("KXMLBSERIES") if kalshi is not None else kalshi_events("KXMLBSERIES")
    for ev in evs or []:
        tk = str(ev.get("event_ticker") or "")
        m = re.search(rf"-{_yy(season)}([A-Z]+?)(WC|ALWC|NLWC|ALDS|NLDS|ALCS|NLCS|WS)$", tk)
        if not m:
            continue
        q, ids = {}, []
        for mk in ev.get("markets") or []:
            tid = map_team(mk.get("yes_sub_title"), teams, _ticker_code(mk.get("ticker")))
            if not tid:
                continue
            ids.append(tid)
            if str(mk.get("result") or "").lower() in ("yes", "no"):
                q[tid] = 1.0 if str(mk["result"]).lower() == "yes" else 0.0
                continue
            p = cpm.kalshi_price(mk)
            if p is not None:
                q[tid] = p
        if len(ids) != 2:
            continue
        a, b = sorted(ids)
        pa = _two_way(q.get(a), q.get(b))
        if pa is None:
            continue
        key = (frozenset((a, b)))
        rec = found.setdefault(key, {"teams": [a, b], "round": SERIES_ROUND.get(m.group(2)), "sources": []})
        rec["sources"].append({"source": "kalshi", "p": round(pa, 4), "market": tk})
    for ev in _poly_events(poly_events):
        title = str(ev.get("title") or "")
        if not re.search(r"Who Will Win Series", title, re.I) or ev.get("closed"):
            continue
        for mk in ev.get("markets") or []:
            outs = mk.get("outcomes")
            if isinstance(outs, str):
                try:
                    outs = json.loads(outs)
                except ValueError:
                    outs = None
            if not outs or len(outs) != 2:
                continue
            ta, tb = map_team(outs[0], teams), map_team(outs[1], teams)
            p = cpm.poly_price(mk)
            if not ta or not tb or p is None:
                continue
            a, b = sorted((ta, tb))
            pa = p if ta == a else 1.0 - p
            rec = found.setdefault(frozenset((a, b)), {"teams": [a, b], "round": None, "sources": []})
            rec["sources"].append({"source": "polymarket", "p": round(pa, 4), "market": ev.get("slug")})
    out = []
    for rec in found.values():
        ps = [x["p"] for x in rec["sources"]]
        p = sum(ps) / len(ps)
        a, b = rec["teams"]
        rec["probs"] = {a: round(p, 4), b: round(1 - p, 4)}
        out.append(rec)
    return out


def futures(season: int | None = None, store: dict | None = None, poly_events: list[dict] | None = None,
            kalshi: dict | None = None) -> dict:
    """{"champion": TITLE, "pennant": {"AL": TITLE, "NL": TITLE}, "awards": {kind: TITLE}, "advance": {...},
    "series": [...], "season", "generated_at"}. Never raises."""
    season = int(season or season_for())
    s = store if store is not None else _load_store(season)
    pev = _poly_events(poly_events)
    out: dict[str, Any] = {"season": season, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    out["champion"] = title_prices(season, "champion", s, pev, kalshi)
    out["pennant"] = {lg: title_prices(season, lg, s, pev, kalshi) for lg in ("AL", "NL")}
    out["awards"] = {k: title_prices(season, k, s, pev, kalshi) for k in AWARD_KINDS}
    try:
        out["advance"] = advance_prices(season, s, pev)
    except Exception as exc:  # noqa: BLE001
        out["advance"] = {"error": str(exc)}
    try:
        out["series"] = series_prices(season, s, pev, kalshi)
    except Exception as exc:  # noqa: BLE001
        out["series"] = []
        logger.info("series prices failed: %s", exc)
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
    """De-vigged P(home) from American moneylines (multiplicative)."""
    ph, pa = american_to_p(home), american_to_p(away)
    if ph is None or pa is None:
        return None
    return _dv.normalise_pair(ph, pa)          # common/edge/devig.py


def store_lines(g: dict, which: str = "close") -> dict:
    """{"p_home", "total", "p_over", "rl_home", "p_rl_home"} from GAME.lines (close, else open, else current)."""
    L = g.get("lines") or {}
    src = L.get(which) or {}
    if not src and which == "close":
        src = L
    out = {}
    ml = src.get("ml") or (L.get("ml") if which != "open" else None)
    if isinstance(ml, (list, tuple)) and len(ml) == 2:
        out["p_home"] = devig_ml(ml[0], ml[1])
    elif isinstance(ml, dict):
        out["p_home"] = devig_ml(ml.get("home"), ml.get("away"))
    tot = src.get("total") or (L.get("total") if which != "open" else None)
    if isinstance(tot, dict):
        line = tot.get("line") if tot.get("line") is not None else tot.get("points")
        po, pu = american_to_p(tot.get("over")), american_to_p(tot.get("under"))
        if line is not None:
            try:
                out["total"] = float(line)
            except (TypeError, ValueError):
                pass
        if po is not None and pu is not None:
            out["p_over"] = po / (po + pu)
    elif isinstance(tot, (int, float, str)):
        try:
            out["total"] = float(tot)
        except (TypeError, ValueError):
            pass
    rl = src.get("rl") or (L.get("rl") if which != "open" else None)
    if isinstance(rl, dict):
        # builder A's record: {"home": home run line (e.g. -1.5), "price": [home american, away american]}
        line = rl.get("home") if not isinstance(rl.get("home"), dict) else None
        price = rl.get("price") if isinstance(rl.get("price"), (list, tuple)) else [None, None]
        ph, pa = american_to_p(price[0]), american_to_p(price[1] if len(price) > 1 else None)
        if line is not None:
            try:
                out["rl_home"] = float(line)
            except (TypeError, ValueError):
                pass
        if ph is not None and pa is not None:
            out["p_rl_home"] = ph / (ph + pa)
            if run_line_swapped(out.get("p_home"), out.get("rl_home"), out["p_rl_home"]):
                out["p_rl_home"] = 1.0 - out["p_rl_home"]
    return {k: (round(v, 5) if isinstance(v, float) else v) for k, v in out.items() if v is not None}


def run_line_swapped(p_home: float | None, rl_home: float | None, p_rl_home: float | None) -> bool:
    """
    True when a run line's two prices are stored the wrong way round. Winning by two or more is a subset of
    winning, and winning or losing by one a superset, so P(home -1.5) < P(home wins) < P(home +1.5) for any
    de-vigged prices; ESPN's records break that order in 4-14% of closing lines (2016-2026) and 14-20% of
    opening lines (2024-2026), always with the two prices exchanged (those games' home -1.5 covered 33% of the
    time against the stored 63%). Needs the same record's moneyline; False without it.
    """
    if p_home is None or rl_home is None or p_rl_home is None:
        return False
    if rl_home < 0:
        return p_rl_home > p_home
    if rl_home > 0:
        return p_rl_home < p_home
    return False


def _games_on(s: dict, d: date) -> list[dict]:
    out = []
    for g in (s.get("games") or {}).values():
        try:
            gd = date.fromisoformat(str(g.get("date"))[:10])
        except ValueError:
            continue
        if abs((gd - d).days) <= 1:
            out.append(g)
    return out


def _match(cands: list[dict], a: str | None, b: str | None, d: date | None) -> dict | None:
    if not a or not b:
        return None
    hit = [g for g in cands if {str(g.get("home")), str(g.get("away"))} == {a, b}]
    if d:
        exact = [g for g in hit if str(g.get("date"))[:10] == d.isoformat()]
        hit = exact or hit
    hit.sort(key=lambda g: (str(g.get("date")), str(g.get("gpk"))))
    return hit[0] if hit else None


def _outs(m: dict) -> list | None:
    outs = m.get("outcomes")
    if isinstance(outs, str):
        try:
            outs = json.loads(outs)
        except ValueError:
            return None
    return outs if isinstance(outs, list) else None


def game_prices(d: Any = None, store: dict | None = None, poly_events: list[dict] | None = None,
                kalshi: dict | None = None) -> dict[str, dict]:
    """
    {gpk: {"home","away","p_home","basis","sources":[...], "total": {"kalshi": {line: P(over)}, "polymarket": {...},
    "draftkings": {...}}, "runline": {...}, "f5": {"home","away","tie", "sources"}}} for the store's games on day d
    (+-1 day). p_home: mean of the prediction-market sources, else the de-vigged DraftKings moneyline. Never raises.
    """
    try:
        d = d if isinstance(d, date) else (date.fromisoformat(str(d)[:10]) if d else datetime.now(timezone.utc).date())
        s = store if store is not None else _load_store(d.year)
        teams = _real(s.get("teams") or {})
        cands = _games_on(s, d)
        out: dict[str, dict] = {}

        def rec(g):
            gid = str(g.get("gpk"))
            if gid not in out:
                out[gid] = {"home": str(g["home"]), "away": str(g["away"]), "date": g.get("date"), "sources": [],
                            "total": {}, "runline": {}, "f5": {"sources": []}, "nrfi": {}}
            return out[gid]

        kev = (lambda k: (kalshi or {}).get(k)) if kalshi is not None else kalshi_events
        for ev in kev("KXMLBGAME") or []:
            ed = kalshi_game_date(ev.get("event_ticker"))
            if ed and abs((ed - d).days) > 1:
                continue
            q, ids = {}, []
            for m in ev.get("markets") or []:
                tid = map_team(m.get("yes_sub_title"), teams, _ticker_code(m.get("ticker")))
                if tid:
                    ids.append(tid)
                    p = cpm.kalshi_price(m)
                    if p is not None:
                        q[tid] = p
            g = _match(cands, *(ids + [None, None])[:2], ed)
            if not g or not q:
                continue
            h, a = str(g["home"]), str(g["away"])
            ph = _two_way(q.get(h), q.get(a))
            if ph is not None:
                rec(g)["sources"].append({"source": "kalshi", "p_home": round(ph, 4), "market": ev.get("event_ticker")})
        for series, kind in (("KXMLBTOTAL", "total"), ("KXMLBSPREAD", "spread")):
            for ev in kev(series) or []:
                tk = str(ev.get("event_ticker") or "")
                ed = kalshi_game_date(tk)
                if ed and abs((ed - d).days) > 1:
                    continue
                mm = re.search(r"\d{4}([A-Z]+)$", tk)
                codes = mm.group(1) if mm else ""
                g = None
                for k in range(2, len(codes) - 1):
                    ta, tb = map_team(None, teams, codes[:k]), map_team(None, teams, codes[k:])
                    if ta and tb:
                        g = _match(cands, ta, tb, ed)
                        if g:
                            break
                if not g:
                    continue
                r = rec(g)
                if kind == "total":
                    lad = {}
                    for m in ev.get("markets") or []:
                        p = cpm.kalshi_price(m)
                        try:
                            line = float(m.get("floor_strike"))
                        except (TypeError, ValueError):
                            continue
                        if p is not None:
                            lad[line] = round(p, 4)
                    if lad:
                        r["total"]["kalshi"] = dict(sorted(lad.items()))
                else:
                    lad = {}
                    for m in ev.get("markets") or []:
                        p = cpm.kalshi_price(m)
                        code = re.sub(r"\d+$", "", _ticker_code(m.get("ticker")) or "")
                        tid = map_team(None, teams, code)
                        try:
                            line = float(m.get("floor_strike"))
                        except (TypeError, ValueError):
                            continue
                        if p is not None and tid:
                            side = "home" if tid == str(g["home"]) else "away"
                            lad.setdefault(side, {})[line] = round(p, 4)
                    if lad:
                        r["runline"]["kalshi"] = lad
        for ev in _poly_events(poly_events):
            slug = str(ev.get("slug") or "")
            mm = re.fullmatch(r"mlb-([a-z]+)-([a-z]+)-(\d{4}-\d{2}-\d{2})(-first-five-winner)?", slug)
            if not mm or ev.get("closed"):
                continue
            ed = date.fromisoformat(mm.group(3))
            if abs((ed - d).days) > 1:
                continue
            ta, tb = map_team(None, teams, mm.group(1).upper()), map_team(None, teams, mm.group(2).upper())
            g = _match(cands, ta, tb, ed)
            if not g:
                continue
            r = rec(g)
            h, a = str(g["home"]), str(g["away"])
            if mm.group(4):
                q = {}
                for m in ev.get("markets") or []:
                    lab = str(m.get("groupItemTitle") or "")
                    p = cpm.poly_price(m)
                    if p is None:
                        continue
                    if lab.lower() in ("draw", "tie"):
                        q["tie"] = p
                    else:
                        t = map_team(lab, teams)
                        if t:
                            q["home" if t == h else "away"] = p
                if len(q) == 3:
                    tot = sum(q.values())
                    r["f5"]["sources"].append({"source": "polymarket", **{k: round(v / tot, 4) for k, v in q.items()},
                                               "market": slug})
                continue
            for m in ev.get("markets") or []:
                smt = str(m.get("sportsMarketType") or "")
                outs = _outs(m)
                p = cpm.poly_price(m)
                if p is None or not outs:
                    continue
                if smt == "moneyline" and len(outs) == 2:
                    o0 = map_team(outs[0], teams)
                    ph = p if o0 == h else 1.0 - p
                    r["sources"].append({"source": "polymarket", "p_home": round(ph, 4), "market": slug})
                elif smt in ("totals", "baseball_team_first_five_total"):
                    try:
                        line = float(m.get("line"))
                    except (TypeError, ValueError):
                        continue
                    po = p if str(outs[0]).lower().startswith("over") else 1.0 - p
                    dest = r["total"] if smt == "totals" else r["f5"].setdefault("total", {})
                    dest.setdefault("polymarket", {})[line] = round(po, 4)
                elif smt in ("spreads", "baseball_team_first_five_spread"):
                    try:
                        line = float(m.get("line"))
                    except (TypeError, ValueError):
                        continue
                    t0 = map_team(outs[0], teams)
                    if not t0:
                        continue
                    side = "home" if t0 == h else "away"
                    dest = r["runline"] if smt == "spreads" else r["f5"].setdefault("spread", {})
                    # P(side covers `line`), e.g. home -1.5 -> P(home wins by 2+)
                    dest.setdefault("polymarket", {}).setdefault(side, {})[line] = round(p, 4)
                elif smt == "nrfi":
                    r["nrfi"]["polymarket_yes_run"] = round(p, 4)
        for g in cands:
            ln = store_lines(g, "close") or store_lines(g, "current")
            if ln.get("p_home") is not None:
                r = rec(g)
                r["sources"].append({"source": "draftkings_ml", "p_home": ln["p_home"], "market": "espn"})
                if ln.get("total") is not None:
                    r["total"]["draftkings"] = {"line": ln["total"], "p_over": ln.get("p_over")}
                if ln.get("rl_home") is not None:
                    r["runline"]["draftkings"] = {"home_line": ln["rl_home"], "p_home_cover": ln.get("p_rl_home")}
        for gid, r in out.items():
            pm = [x["p_home"] for x in r["sources"] if x["source"] in ("kalshi", "polymarket")]
            dk = [x["p_home"] for x in r["sources"] if x["source"] == "draftkings_ml"]
            pick = pm or dk
            r["p_home"] = round(sum(pick) / len(pick), 4) if pick else None
            r["basis"] = "prediction_markets" if pm else ("draftkings_ml" if dk else None)
            fs = r["f5"]["sources"]
            if fs:
                for k in ("home", "away", "tie"):
                    r["f5"][k] = round(sum(x[k] for x in fs) / len(fs), 4)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("mlb game_prices failed: %s", exc)
        return {}


def edge(model_p: float | None, market_p: float | None) -> float | None:
    """model / market - 1 (None when either is missing)."""
    if model_p is None or market_p is None or market_p <= 0:
        return None
    return round(model_p / market_p - 1.0, 4)


def compare_titles(model: dict[str, float], title: dict) -> list[dict]:
    """Rows {"id","model","market","edge"} for a TITLE dict against model probabilities."""
    probs = (title or {}).get("probs") or {}
    rows = []
    for k in sorted(set(model) | set(probs), key=lambda x: -(model.get(x) or 0)):
        m, q = model.get(k), probs.get(k)
        rows.append({"id": k, "model": m, "market": q, "edge": edge(m, q) if title.get("available") else None})
    return rows
