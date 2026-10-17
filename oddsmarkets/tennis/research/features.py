"""
Walk-forward match features for the tennis edge research. Every feature of a match is computed from the
matches strictly before it in the timeline (date, round order, id), so it is known before the first ball.

Per player, before each match:
* rest and load: days since the last match (any level, qualifying and Challenger / WTA 125 included), matches in
  the last 7 / 14 / 30 days, games and sets played in the last 3 and 7 days, minutes in the last 3 / 7 days (WTA
  only: durations exist from 2020), the games and sets of the previous match when it was in the same event,
  whether that match was the day before or the same day;
* injury and return: the last match ended with the player retiring or defaulting (and days since), a walkover
  given in the last 30 days, a layoff of 60+ / 120+ days before this match and matches since the return;
* entry: the player came through qualifying in this event (played a Q-round match of the same event);
* form: an exponentially decayed mean of (result - Elo expected) over recent matches (match-count half-life);
* margin of victory: a game-share Elo (rating moves by the share of games won against the share expected), overall
  and surface blended;
* head to head: earlier wins of each over the other (any level, retirements count, walkovers not);
* home: the player's country equals the event's (IOC codes, the store's country strings folded);
* event pace: the event's tiebreak rate per set over earlier editions (a ball/court speed and altitude proxy).

`build(tour)` -> DataFrame keyed by match id with columns "<feature>_1" / "<feature>_2" for the store's p1 / p2,
plus event-level columns; `orient(base, feats)` joins them to the base frame as A/B (and A-B differences).
"""
from __future__ import annotations

import math
import unicodedata
from collections import defaultdict, deque
from datetime import date

import numpy as np
import pandas as pd

from oddsmarkets.tennis.models import _io
from oddsmarkets.tennis.research import base as B

ROUND_ORDER = _io.ROUND_ORDER if hasattr(_io, "ROUND_ORDER") else {}

COUNTRY = {
    "USA": "USA", "UNITED STATES": "USA", "FRANCE": "FRA", "AUSTRALIA": "AUS", "SPAIN": "ESP", "GERMANY": "GER",
    "ENGLAND": "GBR", "GREAT BRITAIN": "GBR", "UK": "GBR", "UNITED KINGDOM": "GBR", "SCOTLAND": "GBR", "WALES": "GBR",
    "ITALY": "ITA", "SWITZERLAND": "SUI", "AUSTRIA": "AUT", "SWEDEN": "SWE", "CANADA": "CAN", "CHINA": "CHN",
    "CHINA PR": "CHN", "NETHERLANDS": "NED", "THE NETHERLANDS": "NED", "HOLLAND": "NED", "MEXICO": "MEX",
    "MONACO": "MON", "BRAZIL": "BRA", "CROATIA": "CRO", "ARGENTINA": "ARG", "RUSSIA": "RUS", "JAPAN": "JPN",
    "MOROCCO": "MAR", "PORTUGAL": "POR", "QATAR": "QAT", "NEW ZEALAND": "NZL", "CHILE": "CHI", "INDIA": "IND",
    "ROMANIA": "ROU", "UNITED ARAB EMIRATES": "UAE", "UAE": "UAE", "BELGIUM": "BEL", "SERBIA": "SRB",
    "BULGARIA": "BUL", "TURKEY": "TUR", "TURKIYE": "TUR", "TUR": "TUR", "KAZAKHSTAN": "KAZ", "THAILAND": "THA",
    "MALAYSIA": "MAS", "ECUADOR": "ECU", "COLOMBIA": "COL", "CZECH REPUBLIC": "CZE", "CZECHIA": "CZE",
    "HUNGARY": "HUN", "POLAND": "POL", "UZBEKISTAN": "UZB", "SLOVENIA": "SLO", "LUXEMBOURG": "LUX",
    "SOUTH KOREA": "KOR", "KOREA": "KOR", "KOREA REPUBLIC": "KOR", "HONG KONG": "HKG", "SLOVAKIA": "SVK",
    "UKRAINE": "UKR", "ISRAEL": "ISR", "SOUTH AFRICA": "RSA", "DENMARK": "DEN", "FINLAND": "FIN", "NORWAY": "NOR",
    "GREECE": "GRE", "CYPRUS": "CYP", "ESTONIA": "EST", "LATVIA": "LAT", "LITHUANIA": "LTU", "BOSNIA": "BIH",
    "BOSNIA AND HERZEGOVINA": "BIH", "MONTENEGRO": "MNE", "TAIWAN": "TPE", "CHINESE TAIPEI": "TPE",
    "SINGAPORE": "SGP", "INDONESIA": "INA", "PHILIPPINES": "PHI", "VIETNAM": "VIE", "SAUDI ARABIA": "KSA",
    "EGYPT": "EGY", "TUNISIA": "TUN", "PERU": "PER", "URUGUAY": "URU", "PARAGUAY": "PAR", "BOLIVIA": "BOL",
    "VENEZUELA": "VEN", "COSTA RICA": "CRC", "PUERTO RICO": "PUR", "IRELAND": "IRL", "BELARUS": "BLR",
    "GEORGIA": "GEO", "ARMENIA": "ARM", "AZERBAIJAN": "AZE", "MOLDOVA": "MDA",
}
US_STATES = {"FLORIDA", "CALIFORNIA", "NEW YORK", "OHIO", "TENNESSEE", "TEXAS", "RHODE ISLAND", "CONNECTICUT",
             "NORTH CAROLINA", "SOUTH CAROLINA", "DC", "GEORGIA", "MASSACHUSETTS", "WASHINGTON", "ILLINOIS",
             "INDIANA", "COLORADO", "ARIZONA", "NEVADA", "VIRGINIA", "MARYLAND", "NEW JERSEY", "PENNSYLVANIA",
             "MICHIGAN", "OREGON", "HAWAII", "UTAH", "ATLANTA", "D.C."}


def fold_country(s) -> str | None:
    if not s or not isinstance(s, str):
        return None
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper().strip()
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts:
        return None
    last = parts[-1]
    if last in COUNTRY:
        return COUNTRY[last]
    if last in US_STATES or (len(parts) >= 2 and parts[-1] in ("USA", "UNITED STATES")):
        return "USA"
    if len(last) == 3 and last.isalpha():
        return last
    return None


def _ord(d: str) -> int:
    return date.fromisoformat(d[:10]).toordinal()


FORM_HL = 8.0          # matches (tuned on 2010-2017 only; see the experiment log)
# game-share Elo (step in logit-of-game-share units, surface weight): chosen per tour on the dev years 2012-2017
# from the grid {0.06, 0.12, 0.24} x {0.2, 0.4, 0.6} (experiment log G1)
GELO = {"atp": (0.06, 0.4), "wta": (0.12, 0.2)}
H2H_MIN = 1


def build(tour: str, form_hl: float = FORM_HL, gk: float | None = None, gw: float | None = None,
          use_cache: bool = True) -> pd.DataFrame:
    t = _io.tour_key(tour)
    gk = GELO[t][0] if gk is None else gk
    gw = GELO[t][1] if gw is None else gw
    tl = B.timeline(t, use_cache=use_cache)
    key = _io.file_key("feat-3", len(tl), str(tl["date"].max()), form_hl, gk, gw)
    p = B._cache(f"tn_feat_{t}", key)
    if use_cache and p.exists():
        return pd.read_parquet(p)
    from oddsmarkets.tennis.models import elo as E
    pre = E.pre_match(E.history(t))
    reg = {}
    for y in _io.years_on_disk(t):
        st = _io.load_store(t, y) or {}
        for pid, pl in (st.get("players") or {}).items():
            if isinstance(pl, dict) and pl.get("country"):
                reg[str(pid)] = str(pl["country"]).upper()

    recent: dict = defaultdict(deque)        # pid -> deque[(ord, games, sets, dur)]
    last: dict = {}                          # pid -> (ord, event, games, sets, retired_flag, wo_given_ord)
    form: dict = {}                          # pid -> (num, den)
    gelo: dict = {}                          # pid -> [all, hard, clay, grass]
    layoff_ret: dict = {}                    # pid -> matches since a 60+ day layoff
    h2h: dict = defaultdict(int)             # (winner, loser) -> wins
    qual_ev: set = set()                     # (pid, event) played qualifying
    wo_given: dict = {}
    SI = {"hard": 1, "clay": 2, "grass": 3}
    out = []
    cols = tl[["id", "date", "event", "round", "level", "surface", "indoor", "bo", "p1", "p2", "winner", "status",
               "g1", "g2", "nsets", "dur", "country", "tid"]].itertuples(index=False, name=None)
    for (mid, d, ev, rnd, lvl, srf, indoor, bo, p1, p2, win, status, g1, g2, ns, dur, ctry, tid) in cols:
        o = _ord(d)
        si = SI.get(srf, 1)
        ec = fold_country(ctry)
        rec = {"id": mid, "home_ev": ec}
        for side, pid, opp in ((1, p1, p2), (2, p2, p1)):
            dq = recent[pid]
            while dq and dq[0][0] < o - 30:
                dq.popleft()
            ls = last.get(pid)
            rec[f"days_{side}"] = (o - ls[0]) if ls else np.nan
            rec[f"m7_{side}"] = sum(1 for x in dq if x[0] >= o - 7)
            rec[f"m14_{side}"] = sum(1 for x in dq if x[0] >= o - 14)
            rec[f"m30_{side}"] = len(dq)
            rec[f"g3_{side}"] = sum(x[1] for x in dq if x[0] >= o - 3)
            rec[f"g7_{side}"] = sum(x[1] for x in dq if x[0] >= o - 7)
            rec[f"s3_{side}"] = sum(x[2] for x in dq if x[0] >= o - 3)
            rec[f"min3_{side}"] = sum(x[3] for x in dq if x[0] >= o - 3 and x[3] == x[3])
            rec[f"min7_{side}"] = sum(x[3] for x in dq if x[0] >= o - 7 and x[3] == x[3])
            same = ls is not None and ls[1] == ev
            rec[f"prev_games_{side}"] = ls[2] if same else np.nan
            rec[f"prev_sets_{side}"] = ls[3] if same else np.nan
            rec[f"b2b_{side}"] = int(same and o - ls[0] <= 1)
            rec[f"ret_last_{side}"] = int(bool(ls and ls[4]))
            rec[f"ret_days_{side}"] = (o - ls[0]) if (ls and ls[4]) else np.nan
            rec[f"wo_given30_{side}"] = int(pid in wo_given and o - wo_given[pid] <= 30)
            rec[f"since_layoff_{side}"] = layoff_ret.get(pid, 99)
            rec[f"layoff60_{side}"] = int(bool(ls) and o - ls[0] >= 60)
            rec[f"layoff120_{side}"] = int(bool(ls) and o - ls[0] >= 120)
            rec[f"qual_{side}"] = int((pid, ev) in qual_ev and lvl != "q")
            f_ = form.get(pid)
            rec[f"form_{side}"] = (f_[0] / (f_[1] + 1.0)) if f_ else 0.0
            ge = gelo.get(pid)
            rec[f"gelo_{side}"] = ((gw * ge[si] + (1 - gw) * ge[0]) if ge else np.nan)
            rec[f"gelo_n_{side}"] = ge[4] if ge else 0
            rec[f"h2h_w_{side}"] = h2h[(pid, opp)]
            c = reg.get(pid)
            rec[f"home_{side}"] = int(bool(ec) and c == ec)
        out.append(rec)
        # ---- updates (after the match) ----
        if status == "upcoming" or status == "live":
            continue
        gp = int(g1 + g2)
        for pid in (p1, p2):
            if status != "wo":
                recent[pid].append((o, gp, int(ns), float(dur) if dur == dur else float("nan")))
            ls = last.get(pid)
            if ls and o - ls[0] >= 60:
                layoff_ret[pid] = 0
            elif pid in layoff_ret:
                layoff_ret[pid] = layoff_ret[pid] + (status != "wo")
            loser_retired = status in ("ret", "def") and pid != win
            if status != "wo":
                last[pid] = (o, ev, gp, int(ns), loser_retired)
        if status == "wo":
            loser = p2 if win == p1 else p1
            wo_given[loser] = o
            continue
        if lvl == "q":
            qual_ev.add((p1, ev))
            qual_ev.add((p2, ev))
        loser = p2 if win == p1 else p1
        h2h[(win, loser)] += 1
        # form: decayed mean of result - Elo expectation
        pe = pre.get(mid)
        if pe is not None:
            lam = 0.5 ** (1.0 / form_hl)
            for pid, res, ex in ((p1, float(win == p1), pe), (p2, float(win == p2), 1 - pe)):
                f_ = form.get(pid) or (0.0, 0.0)
                form[pid] = (lam * f_[0] + (res - ex), lam * f_[1] + 1.0)
        # game-share Elo (completed sets only; retirements count at half weight)
        if gp > 0:
            r1 = gelo.setdefault(p1, [0.0, 0.0, 0.0, 0.0, 0])
            r2 = gelo.setdefault(p2, [0.0, 0.0, 0.0, 0.0, 0])
            share = (g1 + 0.5) / (gp + 1.0)
            wgt = (1.0 if status == "done" else 0.5) * min(1.0, gp / 18.0)
            kk = gk * wgt * (1.0 + 3.0 / (1.0 + min(r1[4], r2[4]) / 20.0))     # faster for new players
            for k in (0, si):
                e_ = 1.0 / (1.0 + math.exp(-(r1[k] - r2[k])))
                r1[k] += 4.0 * kk * (share - e_)
                r2[k] -= 4.0 * kk * (share - e_)
            r1[4] += 1
            r2[4] += 1
    df = pd.DataFrame(out)
    tb = _event_tb(t)                      # event pace needs the set scores: a second, cheap pass over the stores
    if tb is not None:
        df = df.merge(tb, on="id", how="left")
    df.to_parquet(p)
    return df


def _event_tb(t: str) -> pd.DataFrame | None:
    """Per match: the tiebreak rate per set of its tournament (tid) over earlier years, smoothed toward the tour."""
    recs = []
    for m in _io.load_matches(t, statuses=None):
        ev = str(m.get("event") or "")
        tid = ev.rsplit("-", 1)[0] if "-" in ev else ev
        y = (_io.day(m.get("date")) or date(2000, 1, 1)).year
        n = k = 0
        if m.get("status") in ("done", "ret"):
            for s in m.get("sets") or []:
                try:
                    a, b = int(s[0]), int(s[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if max(a, b) >= 6:
                    n += 1
                    k += int((a, b) in ((7, 6), (6, 7)))
        recs.append((m["id"], tid, y, k, n, str(m.get("level"))))
    if not recs:
        return None
    df = pd.DataFrame(recs, columns=["id", "tid", "y", "k", "n", "level"])
    agg = df[df.level != "q"].groupby(["tid", "y"])[["k", "n"]].sum().reset_index().sort_values(["tid", "y"])
    agg["ck"] = agg.groupby("tid")["k"].cumsum() - agg["k"]
    agg["cn"] = agg.groupby("tid")["n"].cumsum() - agg["n"]
    tour_rate = float(df.k.sum() / max(df.n.sum(), 1))
    agg["ev_tb_rate"] = (agg["ck"] + 30 * tour_rate) / (agg["cn"] + 30)
    agg["ev_tb_n"] = agg["cn"]
    return df[["id", "tid", "y"]].merge(agg[["tid", "y", "ev_tb_rate", "ev_tb_n"]], on=["tid", "y"], how="left")[
        ["id", "ev_tb_rate", "ev_tb_n"]]


def orient(base: pd.DataFrame, feats: pd.DataFrame, tour: str) -> pd.DataFrame:
    """Join features to the base frame: "<f>_A"/"<f>_B" (A = p2 when flip) and "d_<f>" = A - B."""
    f = feats.set_index("id")
    sides = sorted({c[:-2] for c in f.columns if c.endswith("_1")})
    df = base.join(f, on="id")
    fl = df["flip"].to_numpy()
    for s in sides:
        a1, a2 = df[f"{s}_1"].to_numpy(dtype=float), df[f"{s}_2"].to_numpy(dtype=float)
        df[f"{s}_A"] = np.where(fl, a2, a1)
        df[f"{s}_B"] = np.where(fl, a1, a2)
        df[f"d_{s}"] = df[f"{s}_A"] - df[f"{s}_B"]
        df = df.drop(columns=[f"{s}_1", f"{s}_2"])
    return df
