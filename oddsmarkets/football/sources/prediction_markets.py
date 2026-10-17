"""
Match and title prices from the two public prediction markets, Polymarket and
Kalshi. No API key: both publish read-only JSON, which is also how the World Cup
2026 site priced its markets (scripts/fetch_market_odds.py).

Match lines
    Polymarket lists each fixture as an event in the league's sports series
    ("Arsenal FC vs. Leeds United FC") holding three yes/no "moneyline" markets:
    home win, draw, away win. Kalshi lists it as an event in a `KX...GAME`
    series with three markets (each club and "Tie"). A price is the midpoint of
    the best bid and ask; a market without a live two-sided quote, or with a
    spread over twelve points, is skipped. The three prices are turned
    into decimal odds (1 / p) and handed to `core.markets.build_match_markets`
    as two "books", which de-vigs each and takes the consensus.

Title markets
    Kalshi's champion series (`KXPREMIERLEAGUE`, `KXUCL`, `KXMLSCUP` ...), one
    market per club, and Polymarket's champion event where a search finds one.
    Prices are de-vigged across the field by `build_outright_markets`.

Names
    The markets spell clubs their own way ("Leeds United FC", "Brighton & Hove
    Albion FC", "Leeds United"). A market event is matched to one of our
    fixtures within 36 hours of its kickoff whose two clubs both match the
    market's two names; a title market's clubs are matched against the table.
    Matching folds accents, drops club-form words (FC, AFC, CF, SC, Club...) and
    accepts a token-subset or a close string ratio. Anything ambiguous is left
    out rather than guessed.
"""
from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import requests

logger = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
HEADERS = {"User-Agent": "Mozilla/5.0 (The Quant Footballer; +https://pchattani.github.io/the-quant-footballer/)"}
TIMEOUT = 15
HORIZON_DAYS = 21            # match markets further out than this are not fetched
MAX_SPREAD = 0.12            # a wider bid/ask is not a price

# competition slug -> (Polymarket sport code, Kalshi game series, Kalshi champion series, Polymarket champion slug token)
MARKETS: dict[str, tuple[str | None, str | None, str | None, str | None]] = {
    "premier-league": ("epl", "KXEPLGAME", "KXPREMIERLEAGUE", "epl-"),
    "la-liga": ("lal", "KXLALIGAGAME", "KXLALIGA", "la-liga"),
    "serie-a": ("sea", "KXSERIEAGAME", "KXSERIEA", "serie-a"),
    "bundesliga": ("bun", "KXBUNDESLIGAGAME", "KXBUNDESLIGA", "bundesliga"),
    "ligue-1": ("fl1", "KXLIGUE1GAME", "KXLIGUE1", "ligue-1"),
    "eredivisie": ("ere", "KXEREDIVISIEGAME", "KXEREDIVISIE", None),
    "primeira-liga": ("por", "KXLIGAPORTUGALGAME", "KXLIGAPORTUGAL", None),
    "belgian-pro-league": ("bel1", "KXBELGIANPLGAME", "KXBELGIANPL", None),
    "brasileirao": ("bra", "KXBRASILEIROGAME", "KXBRASILEIRO", None),
    "mls": ("mls", "KXMLSGAME", "KXMLSCUP", "mls-cup"),
    "liga-mx": ("mex", "KXLIGAMXGAME", "KXLIGAMX", None),
    "saudi-pro-league": ("spl", "KXSAUDIPLGAME", None, None),
    "liga-argentina": ("arg", "KXARGPREMDIVGAME", "KXARGPREMDIV", None),
    "champions-league": ("ucl", "KXUCLGAME", "KXUCL", "champions-league"),
    "europa-league": ("uel", "KXUELGAME", "KXUEL", None),
    "conference-league": (None, "KXUECLGAME", "KXUECL", None),
    "libertadores": ("lib", None, None, None),
    "sudamericana": ("sud", None, None, None),
    "concacaf-champions-cup": ("ccc", "KXCONCACAFCCUPGAME", None, None),
    "caf-champions-league": ("cafcl", None, None, None),
    "afc-champions-league": ("acle", None, None, None),
    "club-world-cup": ("cwc", None, None, None),
    "uefa-super-cup": ("usc", None, None, None),
    "campeones-cup": ("ccup", None, None, None),
    "fa-cup": ("efa", None, None, None),
    "efl-cup": ("efl", None, None, None),
    "community-shield": ("ecs", None, None, None),
    "copa-del-rey": ("cdr", None, None, None),
    "supercopa-espana": ("ssc", None, None, None),
    "coppa-italia": ("itc", None, None, None),
    "dfb-pokal": ("dfb", None, None, None),
    "coupe-de-france": ("cde", None, None, None),
    "trophee-des-champions": ("frtc", None, None, None),
    "knvb-beker": ("nlc", None, None, None),
    "taca-de-portugal": ("ptc", None, None, None),
    "supertaca-portugal": ("ptsc", None, None, None),
    "copa-argentina": ("argcopa", None, None, None),
    "us-open-cup": ("usoc", None, None, None),
    "world-cup": ("fifwc", None, None, None),
    "euro": ("euc", None, None, None),
    "copa-america": ("copaam", None, None, None),
    "nations-league": ("unl", "KXUEFANLGAME", None, None),
    "concacaf-nations-league": ("conl", "KXCONCACAFNLGAME", None, None),
    "wc-qual-uefa": ("uef", None, None, None),
    "wc-qual-conmebol": ("con", None, None, None),
    "wc-qual-caf": ("caf", None, None, None),
    "wc-qual-afc": ("afc", None, None, None),
    "friendlies": ("fif", None, None, None),
}

_FORM_WORDS = {
    "fc", "afc", "cf", "sc", "ac", "as", "cd", "ud", "sd", "rc", "rcd", "ca", "club", "de", "del", "la", "le", "the",
    "calcio", "football", "futbol", "futebol", "sport", "sporting", "clube", "fk", "sk", "bk", "if", "ssc", "vfl", "vfb",
    "tsg", "sv", "fsv", "1", "1899", "1846", "1848", "1909", "1913", "04", "05", "07", "96", "saudi", "and",
}
_sports_cache: dict[str, str] | None = None

# Names a market uses that share nothing with the club's usual name (Kalshi
# names Dutch clubs by city). Keys are folded; values are spellings our
# registries use, matched as usual afterwards.
ALIASES = {
    "eindhoven": "PSV", "alkmaar": "AZ", "enschede": "Twente", "nijmegen": "NEC", "arnhem": "Vitesse",
    "man city": "Manchester City", "man utd": "Manchester United", "man united": "Manchester United",
    "spurs": "Tottenham", "wolves": "Wolverhampton", "psg": "Paris Saint-Germain", "inter milan": "Inter",
    "bayern munich": "Bayern", "atletico": "Atletico Madrid", "leverkusen": "Bayer Leverkusen",
}


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None) -> Any:
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            logger.info("prediction markets: %s answered %s", url, r.status_code)
            return None
        return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.info("prediction markets: %s failed: %s", url, exc)
        return None


def _poly_series(code: str) -> str | None:
    global _sports_cache
    if _sports_cache is None:
        rows = _get(f"{GAMMA}/sports") or []
        _sports_cache = {str(r.get("sport")): str(r.get("series")) for r in rows if r.get("series")}
    return _sports_cache.get(code)


# ── names ────────────────────────────────────────────────────────────────────

def fold(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    toks = [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in _FORM_WORDS]
    return " ".join(toks)


def name_score(a: str, b: str) -> float:
    """1.0 for the same club under two spellings, near 0 for different clubs."""
    fa, fb = fold(a), fold(b)
    if not fa or not fb:
        return 0.0
    if fa == fb:
        return 1.0
    ta, tb = set(fa.split()), set(fb.split())
    if ta <= tb or tb <= ta:
        return 0.93
    return difflib.SequenceMatcher(None, fa, fb).ratio()


def best_match(name: str, candidates: Iterable[str], floor: float = 0.72) -> str | None:
    name = ALIASES.get(fold(name), name)
    scored = sorted(((name_score(name, c), c) for c in candidates), reverse=True)
    if not scored or scored[0][0] < floor:
        return None
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 0.02 and scored[1][0] < 1.0:
        return None                                   # two clubs fit equally well: leave it out
    return scored[0][1]


# ── prices ───────────────────────────────────────────────────────────────────

def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _mid(bid, ask, last=None) -> float | None:
    """
    The midpoint of a live two-sided quote, or None. A last trade is not used:
    in a thin market it can be days old (a stale 84% on an Eredivisie outsider
    was the case that settled it), and one bad price skews the whole de-vig.
    """
    b, a = _f(bid), _f(ask)
    if b is not None and a is not None and 0 < b <= a < 1 and a - b <= MAX_SPREAD:
        return (a + b) / 2
    return None


def _poly_price(m: dict) -> float | None:
    return _mid(m.get("bestBid"), m.get("bestAsk"), m.get("lastTradePrice"))


def _kalshi_price(m: dict) -> float | None:
    return _mid(m.get("yes_bid_dollars"), m.get("yes_ask_dollars"), m.get("last_price_dollars"))


def _odds(p: float | None) -> float | None:
    return round(1.0 / p, 4) if p and p > 0 else None


# ── match lines ──────────────────────────────────────────────────────────────

def _parse_time(s) -> datetime | None:
    if not s:
        return None
    text = str(s).strip().replace(" ", "T", 1).replace("Z", "+00:00")
    if re.search(r"[+-]\d\d$", text):
        text += ":00"
    try:
        d = datetime.fromisoformat(text)
    except ValueError:
        try:
            d = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _polymarket_games(code: str, now: datetime) -> list[dict]:
    """[{home, away, kickoff, p: {name: prob, 'draw': prob}}] for one Polymarket series."""
    series = _poly_series(code)
    if not series:
        return []
    out = []
    for offset in (0, 100, 200):
        rows = _get(f"{GAMMA}/events", {"series_id": series, "active": "true", "closed": "false", "limit": 100, "offset": offset,
                                        "end_date_max": (now + timedelta(days=HORIZON_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")}) or []
        for e in rows:
            title = str(e.get("title") or "")
            if " vs. " not in title or " - " in title:
                continue
            lines = [m for m in e.get("markets") or [] if m.get("sportsMarketType") == "moneyline"]
            if len(lines) != 3:
                continue
            home, away = [x.strip() for x in title.split(" vs. ", 1)]
            probs: dict[str, float] = {}
            for m in lines:
                p = _poly_price(m)
                if p is None:
                    break
                label = str(m.get("groupItemTitle") or "")
                probs["draw" if label.lower().startswith("draw") else label] = p
            if len(probs) != 3 or "draw" not in probs:
                continue
            kickoff = _parse_time(e.get("startTime") or (lines[0].get("gameStartTime")) or e.get("endDate"))
            out.append({"home": home, "away": away, "kickoff": kickoff, "p": probs, "src": "polymarket"})
        if len(rows) < 100:
            break
    return out


def _kalshi_games(series: str) -> list[dict]:
    rows = (_get(f"{KALSHI}/events", {"series_ticker": series, "status": "open", "with_nested_markets": "true", "limit": 200}) or {}).get("events") or []
    out = []
    for e in rows:
        title = str(e.get("title") or "")
        if " vs " not in title:
            continue
        home, away = [x.strip() for x in title.split(" vs ", 1)]
        probs: dict[str, float] = {}
        kickoff = None
        for m in e.get("markets") or []:
            p = _kalshi_price(m)
            if p is None:
                continue
            label = str(m.get("yes_sub_title") or "")
            probs["draw" if label.lower() in ("tie", "draw") else label] = p
            kickoff = kickoff or _parse_time(m.get("occurrence_datetime") or m.get("expected_expiration_time"))
        if len(probs) == 3 and "draw" in probs:          # kickoff is approximate (expiry); matching allows 36 hours
            out.append({"home": home, "away": away, "kickoff": kickoff, "p": probs, "src": "kalshi"})
    return out


def match_rows(slug: str, fixtures: list[dict], now: datetime | None = None) -> list[dict]:
    """
    Rows for `build_match_markets`: our fixtures that at least one market
    prices, `{match_id, home, away, commence, books: {source: {home, draw, away}}}`
    in decimal odds. `fixtures` are ours: `{id, home, away, date, status}`.
    """
    code, kseries, _, _ = MARKETS.get(slug, (None, None, None, None))
    if not code and not kseries:
        return []
    now = now or datetime.now(timezone.utc)
    games = (_polymarket_games(code, now) if code else []) + (_kalshi_games(kseries) if kseries else [])
    if not games:
        return []
    upcoming = [f for f in fixtures if f.get("status") in ("scheduled", "notstarted", "live") and f.get("date")]
    rows: dict[str, dict] = {}
    for g in games:
        near = [f for f in upcoming if not g["kickoff"] or abs((_parse_time(f["date"]) - g["kickoff"]).total_seconds()) <= 36 * 3600]
        clubs = {c for f in near for c in (f["home"], f["away"])}
        h, a = best_match(g["home"], clubs), best_match(g["away"], clubs)
        if not h or not a or h == a:
            continue
        fx = next((f for f in near if {f["home"], f["away"]} == {h, a}), None)
        if not fx:
            continue
        side = {}
        for label, p in g["p"].items():
            if label == "draw":
                side["draw"] = p
                continue
            who = best_match(label, [fx["home"], fx["away"]], floor=0.6)
            if who == fx["home"]:
                side["home"] = p
            elif who == fx["away"]:
                side["away"] = p
        if set(side) != {"home", "draw", "away"}:
            continue
        row = rows.setdefault(str(fx["id"]), {"match_id": str(fx["id"]), "home": fx["home"], "away": fx["away"], "commence": fx["date"], "books": {}})
        row["books"][g["src"]] = {k: _odds(v) for k, v in side.items()}
    return list(rows.values())


# ── title markets ────────────────────────────────────────────────────────────

def _kalshi_champion(series: str, season_hint: str | None) -> dict[str, float]:
    rows = (_get(f"{KALSHI}/events", {"series_ticker": series, "status": "open", "with_nested_markets": "true", "limit": 10}) or {}).get("events") or []
    if not rows:
        return {}
    ev = rows[0]
    if len(rows) > 1 and season_hint:                         # Liga MX: Apertura and Clausura side by side
        hint = fold(season_hint)
        ev = max(rows, key=lambda e: sum(1 for t in fold(e.get("title") or "").split() if t in hint.split()))
    return {str(m.get("yes_sub_title")): p for m in ev.get("markets") or [] if (p := _kalshi_price(m)) is not None}


def _polymarket_champion(token: str, name: str) -> dict[str, float]:
    found = _get(f"{GAMMA}/public-search", {"q": f"{name} champion", "limit_per_type": 10, "events_status": "active"}) or {}
    bad = ("women", "top-", "relegat", "2-bundesliga", "austrian", "brazil", "ecuador", "afc-", "league-phase", "home-country", "player", "scorer")
    for e in found.get("events") or []:
        slug = str(e.get("slug") or "")
        if token in slug and ("champion" in slug or "winner" in slug) and not any(b in slug for b in bad):
            return {str(m.get("groupItemTitle") or m.get("question")): p for m in e.get("markets") or [] if (p := _poly_price(m)) is not None}
    return {}


def title_prices(slug: str, name: str, teams: Iterable[str], season_hint: str | None = None) -> dict[str, float]:
    """Decimal odds on each of our clubs to win the competition, averaged across the markets that price it."""
    _, _, kseries, ptoken = MARKETS.get(slug, (None, None, None, None))
    teams = list(teams)
    sources = []
    if kseries:
        sources.append(_kalshi_champion(kseries, season_hint))
    if ptoken:
        sources.append(_polymarket_champion(ptoken, name))
    merged: dict[str, list[float]] = {}
    for src in sources:
        for label, p in src.items():
            club = best_match(label, teams)
            if club:
                merged.setdefault(club, []).append(p)
    probs = {club: sum(ps) / len(ps) for club, ps in merged.items() if sum(ps) > 0}
    # A title market is only a market when most of the field is quoted and the
    # prices add up to roughly one; a handful of quotes is noise, not a price.
    total = sum(probs.values())
    if len(probs) < max(4, len(teams) // 2) or not 0.8 <= total <= 1.3:
        logger.info("%s: title market too thin (%d of %d clubs quoted, sum %.2f)", slug, len(probs), len(teams), total)
        return {}
    return {club: round(1.0 / p, 4) for club, p in probs.items()}
