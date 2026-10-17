"""
Edge research for MLB (docs/research/EDGE_PROTOCOL.md; findings in docs/research/mlb_edge.md).

Pieces, all walk-forward:
* prices      `game_prices(g)`: ESPN's lead book open and close (moneyline, total, run line; the close cleaned of
                in-game lines as in backtest._market) and every pre-game book's last line; `kalshi_table()`: Kalshi
                game-winner bid / ask at the market's open, an hour before first pitch and at first pitch, from
                the hourly candles cached by scripts/mlb_kalshi_history.py (2025-04-16 ->).
* model rows  the cached walk-forward backtest (backtest.run; variant "post" = posted lineups and game-time
                weather, "open" = projected lineups, no wind; backtest.variant_game).
* features    `game_features(season)`: bullpen workload, starter rest, schedule (rest, day after night,
                time-zone travel), weather, platoon share; strictly from data before the game.
* blend       `fit_blend` / `walk_forward`: logistic regression of the result (or of the later price) on the
                market's logit at the decision time plus the model's deviation from it and features, refitted
                monthly on earlier games only.
* totals      `park_debias`: the model's mean deviation from the market total at the venue over earlier games
                (prices already seen), removed from the model's total; the venue-level part of the model's
                deviation was anti-informative (correlation -0.28 with the venue's actual residual, 2016-2026).
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _dio
from oddsmarkets.common.edge import devig as _dv
from oddsmarkets.common import fees as _fees

EPS = 1e-6


# ── prices ───────────────────────────────────────────────────────────────────

def am_to_dec(a) -> float | None:
    """American odds -> decimal; None for missing / zero."""
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    if a == 0 or not math.isfinite(a):
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


def devig2(d1: float | None, d2: float | None) -> tuple[float, float] | None:
    """Two decimal prices -> multiplicative de-vigged probabilities."""
    if not d1 or not d2 or d1 <= 1 or d2 <= 1:
        return None
    return _dv.multiplicative_pair(d1, d2)          # common/edge/devig.py


def _pair(node, a: str, b: str):
    if isinstance(node, (list, tuple)) and len(node) == 2:
        return node[0], node[1]
    if isinstance(node, dict):
        return node.get(a), node.get(b)
    return None, None


def _side(src: dict | None) -> dict:
    """Decimal prices of one lines record {ml, total, rl}: ml_h, ml_a, tot, over, under, rl, rl_h, rl_a."""
    src = src or {}
    out: dict = {}
    h, a = _pair(src.get("ml"), "home", "away")
    out["ml_h"], out["ml_a"] = am_to_dec(h), am_to_dec(a)
    t = src.get("total")
    if isinstance(t, dict):
        line = t.get("line") if t.get("line") is not None else t.get("points")
        try:
            out["tot"] = float(line) if line is not None else None
        except (TypeError, ValueError):
            out["tot"] = None
        out["over"], out["under"] = am_to_dec(t.get("over")), am_to_dec(t.get("under"))
    rl = src.get("rl")
    if isinstance(rl, dict) and not isinstance(rl.get("home"), dict) and rl.get("home") is not None:
        pr = rl.get("price") if isinstance(rl.get("price"), (list, tuple)) else [None, None]
        try:
            out["rl"] = float(rl["home"])
        except (TypeError, ValueError):
            out["rl"] = None
        out["rl_h"], out["rl_a"] = am_to_dec(pr[0]), am_to_dec(pr[1] if len(pr) > 1 else None)
        # prices stored the wrong way round (markets.run_line_swapped): exchange them
        fm, fr = devig2(out.get("ml_h"), out.get("ml_a")), devig2(out.get("rl_h"), out.get("rl_a"))
        if fm and fr and out.get("rl") is not None:
            from oddsmarkets.baseball.sources.markets import run_line_swapped
            if run_line_swapped(fm[0], out["rl"], fr[0]):
                out["rl_h"], out["rl_a"] = out["rl_a"], out["rl_h"]
    return {k: v for k, v in out.items() if v is not None}


TOTAL_RANGE = (5.0, 16.0)


def _sane(p: dict) -> dict:
    """Drop in-game lines (totals outside 5-16, run lines other than +-1.5, moneylines priced beyond 1:12)."""
    p = dict(p)
    if p.get("tot") is not None and not (TOTAL_RANGE[0] <= p["tot"] <= TOTAL_RANGE[1]):
        for k in ("tot", "over", "under"):
            p.pop(k, None)
    if p.get("rl") is not None and abs(abs(p["rl"]) - 1.5) > 1e-9:
        for k in ("rl", "rl_h", "rl_a"):
            p.pop(k, None)
    if p.get("ml_h") and p.get("ml_a") and max(p["ml_h"], p["ml_a"]) > 13:
        p.pop("ml_h"), p.pop("ml_a")
    return p


def game_prices(g: dict) -> dict:
    """
    {"open": {...}, "close": {...}, "books": [{name, ...}], "src": lead book} with decimal prices. The close is the
    lead book's close (else its current line) unless backtest._market finds an in-game line there, in which case
    the close is the median pre-game book (moneyline) and the books at the median total. The open is ESPN's
    recorded open (2023 ->), checked for in-game values the same way.
    """
    from oddsmarkets.baseball.models import backtest as BT
    L = g.get("lines") or {}
    if not L:
        return {}
    books = []
    for b in L.get("books") or []:
        if not isinstance(b, dict) or "live" in str(b.get("name") or "").lower() or str(b.get("id")) in ("1002", "1003", "1004"):
            continue
        p = _sane(_side(b))
        if p:
            books.append({"name": b.get("name")} | p)
    close_src = L.get("close") or {}
    close = _sane(_side(close_src)) if close_src else {}
    cur = _sane(_side(L))
    for k, v in cur.items():
        close.setdefault(k, v)
    mk = BT._market(g)
    if mk.get("cleaned"):
        # the lead book held an in-game line: take each market from the books
        close = {}
        mls = [b for b in books if b.get("ml_h") and b.get("ml_a")]
        if mls:
            fair = [devig2(b["ml_h"], b["ml_a"])[0] for b in mls]
            med = mls[int(np.argsort(fair)[len(fair) // 2])]
            close["ml_h"], close["ml_a"] = med["ml_h"], med["ml_a"]
        if mk.get("total") is not None:
            tb = [b for b in books if b.get("tot") == mk["total"] and b.get("over") and b.get("under")]
            if tb:
                close["tot"] = mk["total"]
                close["over"] = float(np.median([b["over"] for b in tb]))
                close["under"] = float(np.median([b["under"] for b in tb]))
        if mk.get("rl_home") is not None:
            rb = [b for b in books if b.get("rl") == mk["rl_home"] and b.get("rl_h") and b.get("rl_a")]
            if rb:
                close["rl"] = mk["rl_home"]
                close["rl_h"] = float(np.median([b["rl_h"] for b in rb]))
                close["rl_a"] = float(np.median([b["rl_a"] for b in rb]))
    opn = _sane(_side(L.get("open"))) if L.get("open") else {}
    # an open total a run or more from the close is an in-game or mis-keyed line
    if opn.get("tot") is not None and close.get("tot") is not None and abs(opn["tot"] - close["tot"]) >= 2.0:
        for k in ("tot", "over", "under"):
            opn.pop(k, None)
    return {"open": opn, "close": close, "books": books, "src": L.get("src"), "cleaned": bool(mk.get("cleaned"))}


# ── Kalshi ───────────────────────────────────────────────────────────────────

KALSHI_DIR = "kalshi"
MAX_SPREAD = 0.10


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _candle(c: dict) -> tuple[int, float | None, float | None, float]:
    ya, yb = c.get("yes_ask") or {}, c.get("yes_bid") or {}
    ask = _f(ya.get("close_dollars", ya.get("close")))
    bid = _f(yb.get("close_dollars", yb.get("close")))
    vol = _f(c.get("volume_fp", c.get("volume"))) or 0.0
    return int(c["end_period_ts"]), bid, ask, vol


def _quote(rows: list, t_max: int, t_min: int | None = None) -> dict | None:
    """The last two-sided quote (0 < bid <= ask < 1, spread <= MAX_SPREAD) with ts <= t_max (and >= t_min)."""
    best = None
    for ts, bid, ask, _ in rows:
        if ts > t_max or (t_min is not None and ts < t_min):
            continue
        if bid is None or ask is None or not (0 < bid <= ask < 1) or ask - bid > MAX_SPREAD:
            continue
        best = {"ts": ts, "bid": bid, "ask": ask}
    return best


KALSHI_FEE = _fees.KALSHI_TAKER_RATE   # taker fee per $1 contract: 0.07 x P x (1 - P) (common/fees.py; the
                                       # order's round-up to the cent is spread over a bulk order, so not applied)


def kalshi_dec(ask: float | None) -> float | None:
    """Decimal price of buying a Kalshi yes at `ask` dollars, the taker fee included (fractional cents kept)."""
    if ask is None or not (0 < ask < 1) or not math.isfinite(ask):
        return None
    return _fees.kalshi_decimal(ask)


def _first_quote(rows: list, t_max: int) -> dict | None:
    for ts, bid, ask, _ in rows:
        if ts > t_max:
            break
        if bid is not None and ask is not None and 0 < bid <= ask < 1 and ask - bid <= MAX_SPREAD:
            return {"ts": ts, "bid": bid, "ask": ask}
    return None


_MON = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def parse_kalshi_event(event: str, codes: Iterable[str]) -> dict | None:
    """
    KXMLBGAME-26AUG021605DETATH -> {"date": "2026-08-02", "hhmm": "1605" (Eastern; None in early 2025 tickers),
    "away": "DET", "home": "ATH"}: the pair is the away code then the home code; `codes` are the event's market
    suffixes (the two teams), which settle where one code ends and the other begins.
    """
    try:
        body = event.split("-", 1)[1]
        yy, mon, dd = int(body[:2]), _MON[body[2:5]], int(body[5:7])
    except (IndexError, KeyError, ValueError):
        return None
    rest = body[7:]
    hhmm = rest[:4] if rest[:4].isdigit() else None
    teams = rest[4:] if hhmm else rest
    cs = [c for c in codes if c]
    for a in cs:
        for h in cs:
            if a != h and teams == a + h:
                return {"date": f"20{yy:02d}-{mon:02d}-{dd:02d}", "hhmm": hhmm, "away": a, "home": h}
    return None


def kalshi_table(root: Path | None = None) -> pd.DataFrame:
    """
    One row per Kalshi game: event, ticker date (Eastern) and time, away / home codes, the yes team's code, the
    yes team's result and its hourly candles [(end_ts, bid, ask, volume)] (`kalshi_quotes` turns them into quotes
    once the game's first pitch is known).
    """
    root = root or (_dio.cache_root() / KALSHI_DIR)
    mp = root / "markets.json"
    if not mp.exists():
        return pd.DataFrame()
    ms = json.loads(mp.read_text())
    by_ev: dict[str, list] = {}
    for m in ms:
        by_ev.setdefault(m["event_ticker"], []).append(m)
    out = []
    for ev, mm in by_ev.items():
        mm = sorted(mm, key=lambda m: m["ticker"])
        m = mm[0]
        cp = root / "candles" / f"{m['ticker']}.json"
        if not cp.exists():
            continue
        try:
            cs = json.loads(cp.read_text())
        except Exception:  # noqa: BLE001
            continue
        codes = [x["ticker"].rsplit("-", 1)[-1] for x in mm]
        info = parse_kalshi_event(ev, codes)
        if not info:
            continue
        rows = sorted((_candle(c) for c in cs if c.get("end_period_ts")), key=lambda r: r[0])
        out.append({"event": ev, "code": codes[0], **info,
                    "result": 1.0 if m.get("result") == "yes" else (0.0 if m.get("result") == "no" else np.nan),
                    "candles": rows})
    return pd.DataFrame(out)


def kalshi_quotes(rows: list, start_ts: int) -> dict:
    """
    Quotes of the yes team relative to first pitch: "open" the first two-sided quote ending at least an hour
    before, "1h" the last ending 1-4 h before, "close" the last ending in the 2 h before first pitch; volume
    traded before first pitch.
    """
    out: dict = {"volume_pre": float(sum(v for ts, _, _, v in rows if ts <= start_ts))}
    for name, q in (("open", _first_quote(rows, start_ts - 3600)), ("1h", _quote(rows, start_ts - 3600, start_ts - 4 * 3600)),
                    ("close", _quote(rows, start_ts, start_ts - 2 * 3600))):
        if q:
            out[f"{name}_bid"], out[f"{name}_ask"], out[f"{name}_ts"] = q["bid"], q["ask"], q["ts"]
    return out


def match_kalshi(kt: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """
    Attach Kalshi games to store games (gpk, date, home_abbr, away_abbr, start_time): same home and away teams
    (Kalshi codes through markets.CODE_ALIASES) on the ticker's date or the day either side, doubleheaders by the
    ticker's Eastern time when it has one (else the order of the starts). Quotes are taken relative to the store's
    first pitch. Adds k_home (1 when Kalshi's yes team is the home team).
    """
    from oddsmarkets.baseball.sources.markets import CODE_ALIASES
    if not len(kt) or not len(games):
        return pd.DataFrame()

    def norm(c):
        c = str(c or "").upper()
        return CODE_ALIASES.get(c, c)
    g = games.copy()
    g["h"], g["a"] = g["home_abbr"].map(norm), g["away_abbr"].map(norm)
    g["st"] = pd.to_datetime(g["start_time"], utc=True)
    # Eastern date / time of first pitch (UTC-4 in season; good enough to pick between the two games of a day)
    g["et"] = g["st"] - pd.Timedelta(hours=4)
    idx: dict = {}
    for r in g.itertuples():
        idx.setdefault((r.h, r.a), []).append(r)
    out = []
    used = set()
    for k in kt.sort_values(["date", "hhmm"], na_position="first").itertuples():
        h, a = norm(k.home), norm(k.away)
        d0 = date.fromisoformat(k.date)
        cands = [r for r in idx.get((h, a), []) if abs((r.et.date() - d0).days) <= 1 and r.gpk not in used]
        if not cands:
            continue
        if isinstance(k.hhmm, str) and k.hhmm:
            target = pd.Timestamp(f"{k.date} {k.hhmm[:2]}:{k.hhmm[2:]}", tz="UTC")
            r = min(cands, key=lambda r: abs((r.et.tz_localize(None) - target.tz_localize(None)).total_seconds()))
        else:
            same = [r for r in cands if r.et.date() == d0] or cands
            r = min(same, key=lambda r: r.st)
        used.add(r.gpk)
        q = kalshi_quotes(k.candles, int(r.st.timestamp()))
        out.append({"gpk": r.gpk, "k_home": int(norm(k.code) == h), "event": k.event} | q)
    return pd.DataFrame(out)


# ── model rows ───────────────────────────────────────────────────────────────

def model_rows(seasons: Iterable[int], variant: str = "post", n_sims: int = 1000) -> pd.DataFrame:
    """The cached walk-forward backtest rows of `variant` (missing seasons skipped)."""
    from oddsmarkets.baseball.models import backtest as BT
    out = []
    for s in seasons:
        p = _dio.cache_root() / "backtest" / BT.cache_name("mlb", s, n_sims, variant)
        if not p.exists():
            continue
        res = json.loads(p.read_text())
        for r in res.get("games") or []:
            out.append({"season": s, "gpk": str(r["gpk"]), "date": r["date"], "gtype": r["gtype"], "home": r["home"],
                        "away": r["away"], "y": r["y"], "model": r["model"], "ratings": r["ratings"],
                        "margin": r["margin"], "total": r["total"], "model_total": r["model_total"],
                        "total_dist": r.get("total_dist"), "margin_dist": r.get("margin_dist"),
                        "sp_h": (r.get("sp") or [None, None])[0], "sp_a": (r.get("sp") or [None, None])[1]})
    return pd.DataFrame(out)


def p_over(total_dist: list, line: float) -> float | None:
    """P(total > line | not a push) from a simulated distribution of totals 0..30."""
    if total_dist is None or line is None:
        return None
    d = np.asarray(total_dist, float)
    k = np.arange(len(d))
    over, under = d[k > line].sum(), d[k < line].sum()
    return float(over / (over + under)) if over + under > 0 else None


def shift_dist(dist: list, delta: float) -> np.ndarray:
    """A distribution of totals 0..n-1 moved by `delta` runs (linear interpolation of the CDF; mass kept)."""
    d = np.asarray(dist, float)
    x = np.arange(len(d))
    c = np.interp(x, x + delta, np.cumsum(d), left=0.0, right=1.0)
    out = np.diff(np.concatenate([[0.0], c]))
    out[-1] += 1.0 - c[-1]
    out = np.clip(out, 0.0, None)
    return out / max(out.sum(), 1e-12)


def p_cover(margin_dist: dict, line: float) -> float | None:
    """P(home margin + line > 0 | not a push)."""
    if not margin_dist or line is None:
        return None
    win = sum(v for k, v in margin_dist.items() if int(k) + line > 0)
    lose = sum(v for k, v in margin_dist.items() if int(k) + line < 0)
    return float(win / (win + lose)) if win + lose > 0 else None


# ── features ─────────────────────────────────────────────────────────────────

def _tz_hours(lon: float | None) -> float:
    return 0.0 if lon is None else float(lon) / 15.0


def game_features(season: int, store: dict | None = None) -> pd.DataFrame:
    """
    Per game, from data strictly before it (the PA table to the day before, the schedule's earlier games):
      bp3_h / bp3_a    relievers' pitches over the previous three days
      bpy_h / bpy_a    relievers who pitched yesterday
      sp_rest_h / _a   starter's days since his previous appearance (capped at 10; 5 when unknown)
      rest_h / rest_a  days since the team's previous game (capped at 3)
      dan_h / dan_a    day game (first pitch before 21:00 UTC) after a night game (previous start at or after 22:00 UTC)
      tz_h / tz_a      |time-zone shift| in hours from the team's previous venue
      temp, wind_out   game-time report (wind out positive, mph x direction; 0 under a roof)
      plat_h / plat_a  share of the posted lineup with the platoon edge over the opposing starter (post-lineup only)
    """
    from oddsmarkets.baseball.models import game_inputs as GI
    from oddsmarkets.baseball.models import game_sim as G
    from oddsmarkets.baseball.models import projections as PJ
    store = store if store is not None else _dio.load_store("mlb", season)
    pa = PJ.pa_table("mlb", season)
    prev = PJ.pa_table("mlb", season - 1)
    if len(prev):
        tail = prev[prev["game_date"] >= str(date.fromisoformat(str(prev["game_date"].max())[:10]) - timedelta(days=10))]
        pa = pd.concat([tail, pa], ignore_index=True)
    apps, _ = GI.usage_from_pa(pa) if len(pa) else (pd.DataFrame(), None)
    a2t, t2a = GI.abbr_map(store, pa if len(pa) else None)
    venues = store.get("venues") or {}
    players = store.get("players") or {}
    games = [g for g in (store.get("games") or {}).values() if g.get("status") == "final" and g.get("hs") is not None]
    games.sort(key=lambda g: (str(g.get("start") or g.get("date")), str(g.get("gpk"))))
    rel = apps[~apps["start"].astype(bool)] if len(apps) else apps
    rel_by = {k: v for k, v in rel.groupby("team")} if len(rel) else {}
    sp_by = {k: v.sort_values("date") for k, v in apps.groupby("pitcher")} if len(apps) else {}
    last: dict[str, dict] = {}
    out = []
    for g in games:
        d = str(g["date"])[:10]
        dd = date.fromisoformat(d)
        st = str(g.get("start") or "")
        try:
            sdt = datetime.fromisoformat(st.replace("Z", "+00:00"))
        except ValueError:
            sdt = None
        row = {"gpk": str(g["gpk"]), "season": season}
        ven = venues.get(str(g.get("venue") or "")) or {}
        for side in ("home", "away"):
            tid = str(g[side])
            ab = t2a.get(tid, tid)
            s = side[0]
            r = rel_by.get(ab)
            if r is not None:
                w = r[(r["date"] < d) & (r["date"] >= (dd - timedelta(days=3)).isoformat())]
                row[f"bp3_{s}"] = float(w["pitches"].sum())
                row[f"bpy_{s}"] = float((w["date"] == (dd - timedelta(days=1)).isoformat()).sum())
            sp = (g.get("probables") or {}).get(side)
            rest = 5.0
            if sp and str(sp) in sp_by:
                h = sp_by[str(sp)]
                h = h[h["date"] < d]
                if len(h):
                    rest = float(min(10, (dd - date.fromisoformat(str(h["date"].iloc[-1]))).days))
            row[f"sp_rest_{s}"] = rest
            lp = last.get(tid)
            if lp:
                row[f"rest_{s}"] = float(min(3, (dd - lp["date"]).days))
                row[f"dan_{s}"] = float(bool(sdt and lp["start"] and lp["start"].hour >= 22 and sdt.hour < 21
                                             and (dd - lp["date"]).days == 1))
                row[f"tz_{s}"] = abs(_tz_hours(ven.get("lon")) - _tz_hours(lp["lon"])) if ven.get("lon") is not None and lp["lon"] is not None else 0.0
            else:
                row[f"rest_{s}"], row[f"dan_{s}"], row[f"tz_{s}"] = 3.0, 0.0, 0.0
        roof = ven.get("roof")
        tw = G.weather_terms(g.get("weather"), roof)
        row["temp"] = (tw[0] + 70.0) if tw else 70.0
        row["wind_out"] = tw[1] if tw else 0.0
        prob = g.get("probables") or {}
        lus = g.get("lineups") or {}
        for side, opp in (("home", "away"), ("away", "home")):
            sp = prob.get(opp)
            th = ((players.get(str(sp)) or {}).get("throws") or "R")[:1] if sp else "R"
            lu = lus.get(str(g[side])) or []
            if len(lu) >= 9:
                edge = 0
                for b in lu[:9]:
                    bats = ((players.get(str(b)) or {}).get("bats") or "R")[:1]
                    edge += 1 if (bats == "S" or bats != th) else 0
                row[f"plat_{side[0]}"] = edge / 9.0
        out.append(row)
        for side in ("home", "away"):
            last[str(g[side])] = {"date": dd, "start": sdt, "lon": ven.get("lon")}
    return pd.DataFrame(out)


def _framing_rates(season: int, k_called: float = 3000.0) -> dict[str, float]:
    """Catcher -> framing runs per called pitch in `season`, shrunk toward 0 with k called pitches."""
    p = _dio.cache_root() / "framing" / f"mlb_{season}.json"
    if not p.exists():
        return {}
    try:
        t = json.loads(p.read_text())["result"]["catchers"]
    except Exception:  # noqa: BLE001
        return {}
    cols = t["cols"]
    i_p, i_c, i_r = cols.index("pid"), cols.index("called"), cols.index("runs")
    return {str(r[i_p]): float(r[i_r]) / (float(r[i_c]) + k_called) for r in t["rows"]}


def extra_features(season: int, store: dict | None = None) -> pd.DataFrame:
    """
    Per game, from earlier seasons only:
      frame_h / frame_a  framing runs per game of the team's starting catcher (the catcher of the first pitch the
                         team fielded; known once lineups post), from his previous-season framing rate (shrunk,
                         3,000 called pitches) x 70 called pitches a game
      stuff_h / stuff_a  the starter's previous-season Stuff+ (100 = average; 100 when unknown)
      ump_runs           the plate umpire's runs per game over the two previous seasons minus the league's, shrunk
                         with 40 games
    """
    from oddsmarkets.baseball.models import projections as PJ
    store = store if store is not None else _dio.load_store("mlb", season)
    out = {str(g["gpk"]): {"gpk": str(g["gpk"])} for g in (store.get("games") or {}).values()}
    # catchers
    fr = _framing_rates(season - 1)
    try:
        pc = _dio.read_pitches("mlb", season, ["game_pk", "inning_topbot", "fielder_2", "at_bat_number", "pitch_number"])
        pc = pc.sort_values(["game_pk", "at_bat_number", "pitch_number"])
    except Exception:  # noqa: BLE001
        pc = None
    if pc is not None and len(pc) and fr:
        first = pc.dropna(subset=["fielder_2"]).groupby(["game_pk", "inning_topbot"])["fielder_2"].first()
        for (gpk, tb), cid in first.items():
            rec = out.get(str(int(gpk)))
            if rec is None:
                continue
            side = "h" if str(tb).lower().startswith("top") else "a"      # the home team fields in the top half
            rec[f"frame_{side}"] = fr.get(str(int(cid)), 0.0) * 70.0
    # starters' Stuff+
    try:
        ss = PJ.stuff_scores("mlb", season - 1)
    except Exception:  # noqa: BLE001
        ss = pd.Series(dtype=float)
    sd = {str(k): float(v) for k, v in ss.items()} if len(ss) else {}
    # umpires
    tot: dict[str, list] = {}
    allr = []
    for s in (season - 2, season - 1):
        st = _dio.load_store("mlb", s)
        for g in (st.get("games") or {}).values():
            if g.get("status") != "final" or g.get("hs") is None or (g.get("gtype") or "R") != "R":
                continue
            r = int(g["hs"]) + int(g["as"])
            allr.append(r)
            if g.get("umpire_hp"):
                tot.setdefault(str(g["umpire_hp"]), []).append(r)
    lg = float(np.mean(allr)) if allr else 9.0
    ump = {u: (sum(v) - lg * len(v)) / (len(v) + 40.0) for u, v in tot.items()}
    for g in (store.get("games") or {}).values():
        rec = out[str(g["gpk"])]
        pr = g.get("probables") or {}
        rec["stuff_h"] = sd.get(str(pr.get("home")), 100.0)
        rec["stuff_a"] = sd.get(str(pr.get("away")), 100.0)
        rec["ump_runs"] = ump.get(str(g.get("umpire_hp")), 0.0)
    return pd.DataFrame(list(out.values()))


# ── blend / residual model ───────────────────────────────────────────────────

def logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + np.exp(-np.asarray(z, float)))


def fit_logistic(X: np.ndarray, y: np.ndarray, offset: np.ndarray | None = None, l2: float = 1.0,
                 w: np.ndarray | None = None) -> np.ndarray:
    """Ridge logistic regression by Newton steps (y may be fractional, e.g. a later de-vigged price)."""
    n, k = X.shape
    off = np.zeros(n) if offset is None else offset
    w = np.ones(n) if w is None else w
    b = np.zeros(k)
    pen = np.full(k, l2)
    for _ in range(50):
        p = sigmoid(X @ b + off)
        g = X.T @ (w * (y - p)) - pen * b
        H = (X.T * (w * p * (1 - p))) @ X + np.diag(pen)
        step = np.linalg.solve(H, g)
        b = b + step
        if np.abs(step).max() < 1e-9:
            break
    return b


def walk_forward(df: pd.DataFrame, cols: list[str], target: str, offset: str, min_train: int = 1500,
                 l2: float = 1.0, by: str = "month") -> np.ndarray:
    """
    Out-of-sample predictions: rows sorted by date, refitted at each new `by` period (month) on every earlier row
    only (expanding window); prediction = sigmoid(offset + X b). Rows before `min_train` training rows keep the
    offset alone (b = 0).
    """
    d = df.sort_values("date")
    per = d["date"].str[:7] if by == "month" else d["season"].astype(str)
    X = d[cols].to_numpy(float) if cols else np.zeros((len(d), 0))
    y = d[target].to_numpy(float)
    off = d[offset].to_numpy(float)
    pred = np.full(len(d), np.nan)
    pv = per.to_numpy()
    keys = list(dict.fromkeys(pv))
    for k in keys:
        test = pv == k
        train = (pv < k) & np.isfinite(y)
        if train.sum() >= min_train and X.shape[1]:
            b = fit_logistic(X[train], y[train], off[train], l2=l2)
        else:
            b = np.zeros(X.shape[1])
        pred[test] = sigmoid(off[test] + (X[test] @ b if X.shape[1] else 0))
    return pd.Series(pred, index=d.index).reindex(df.index).to_numpy()


def park_debias(df: pd.DataFrame, dev_col: str = "dev", k: float = 40.0) -> np.ndarray:
    """
    The model's deviation from the market total with its venue bias removed, walk-forward: each game subtracts
    the shrunk mean deviation at its venue over every earlier game (any season), sum / (n + k). Uses only prices
    and model outputs from before the game.
    """
    d = df.sort_values(["date", "gpk"])
    out = pd.Series(np.nan, index=d.index)
    acc: dict = {}
    for date_, grp in d.groupby("date", sort=True):
        for i, r in grp.iterrows():
            s, n = acc.get(r["venue"], (0.0, 0))
            out[i] = r[dev_col] - (s / (n + k) if n + k > 0 else 0.0)
        for i, r in grp.iterrows():
            s, n = acc.get(r["venue"], (0.0, 0))
            if np.isfinite(r[dev_col]):
                acc[r["venue"]] = (s + r[dev_col], n + 1)
    return out.reindex(df.index).to_numpy()


# ── scores ───────────────────────────────────────────────────────────────────

def logloss(p, y) -> float:
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def boot_ci(x: np.ndarray, groups: np.ndarray | None = None, n: int = 2000, seed: int = 0, stat=np.mean) -> tuple:
    """Percentile bootstrap (resampling groups, e.g. dates, when given): (estimate, lo95, hi95)."""
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    if groups is None:
        est = float(stat(x))
        bs = [float(stat(x[rng.integers(0, len(x), len(x))])) for _ in range(n)]
    else:
        u, inv = np.unique(groups, return_inverse=True)
        sums = np.bincount(inv, weights=x, minlength=len(u))
        cnts = np.bincount(inv, minlength=len(u)).astype(float)
        est = float(sums.sum() / cnts.sum())
        bs = []
        for _ in range(n):
            j = rng.integers(0, len(u), len(u))
            bs.append(float(sums[j].sum() / max(cnts[j].sum(), 1)))
    return est, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
