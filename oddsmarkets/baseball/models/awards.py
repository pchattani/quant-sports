"""
Award races: MVP, Cy Young and Rookie of the Year per league.

Winners 2015-2025 (WINNERS) were checked on 2026-10-01 against Baseball-Reference's award pages
(https://www.baseball-reference.com/awards/mvp.shtml, /cya.shtml, /roy.shtml): every one of the 66 entries
matched (VERIFIED = True). Names are resolved to MLBAM ids at run time from the store / people crosswalk.

Candidates and features (one league-season at a time, regular season only)
    value     Bullpen WAR from builder C's war.py when it is importable; otherwise a proxy:
              hitters  (wOBA - lg wOBA) / 1.20 * PA / 10 + 2.0 * PA / 600       (batting runs over replacement / 10)
              pitchers (lg FIP - FIP) * IP / 9 / 10 + 0.12 * IP / 9             (FIP-based, constant 3.10 + lg offset)
    traditional  hitters: HR, PA; pitchers: K, IP, RA9 (runs allowed while pitching, per nine)
    team      the player's team's win %
Each feature is z-scored within the league-season's candidates. MVP candidates are hitters with >= 300 PA and
pitchers with >= 120 IP (two-way players get both values added); Cy Young: pitchers with >= 40 IP; ROY:
players with no MLB plate appearance (as batter or pitcher) in any earlier season on disk and >= 100 PA or
30 IP (a proxy for rookie status: 130 AB / 50 IP / 45 days).

Model: a conditional logit, P(i wins) = exp(b . x_i) / sum_j exp(b . x_j) over the league-season's candidates,
fitted by maximum likelihood (L2 penalty 0.5) on the verified winners in the seasons with data; defaults
when fewer than four seasons are available. Projection for the current season uses the season to date.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from oddsmarkets.baseball.models import _dio
from oddsmarkets.baseball.models._dio import E

logger = logging.getLogger(__name__)

VERIFIED = True
SOURCE = "https://www.baseball-reference.com/awards/ (mvp.shtml, cya.shtml, roy.shtml), checked 2026-10-01"
WINNERS = {
    "mvp": {
        2015: ("Josh Donaldson", "Bryce Harper"), 2016: ("Mike Trout", "Kris Bryant"),
        2017: ("Jose Altuve", "Giancarlo Stanton"), 2018: ("Mookie Betts", "Christian Yelich"),
        2019: ("Mike Trout", "Cody Bellinger"), 2020: ("Jose Abreu", "Freddie Freeman"),
        2021: ("Shohei Ohtani", "Bryce Harper"), 2022: ("Aaron Judge", "Paul Goldschmidt"),
        2023: ("Shohei Ohtani", "Ronald Acuna Jr."), 2024: ("Aaron Judge", "Shohei Ohtani"),
        2025: ("Aaron Judge", "Shohei Ohtani"),
    },
    "cy": {
        2015: ("Dallas Keuchel", "Jake Arrieta"), 2016: ("Rick Porcello", "Max Scherzer"),
        2017: ("Corey Kluber", "Max Scherzer"), 2018: ("Blake Snell", "Jacob deGrom"),
        2019: ("Justin Verlander", "Jacob deGrom"), 2020: ("Shane Bieber", "Trevor Bauer"),
        2021: ("Robbie Ray", "Corbin Burnes"), 2022: ("Justin Verlander", "Sandy Alcantara"),
        2023: ("Gerrit Cole", "Blake Snell"), 2024: ("Tarik Skubal", "Chris Sale"),
        2025: ("Tarik Skubal", "Paul Skenes"),
    },
    "roy": {
        2015: ("Carlos Correa", "Kris Bryant"), 2016: ("Michael Fulmer", "Corey Seager"),
        2017: ("Aaron Judge", "Cody Bellinger"), 2018: ("Shohei Ohtani", "Ronald Acuna Jr."),
        2019: ("Yordan Alvarez", "Pete Alonso"), 2020: ("Kyle Lewis", "Devin Williams"),
        2021: ("Randy Arozarena", "Jonathan India"), 2022: ("Julio Rodriguez", "Michael Harris II"),
        2023: ("Gunnar Henderson", "Corbin Carroll"), 2024: ("Luis Gil", "Paul Skenes"),
        2025: ("Nick Kurtz", "Drake Baldwin"),
    },
}
FEATURES = {"mvp": ["value", "hr", "team", "woba"], "cy": ["value", "k", "ip", "ra9"], "roy": ["value", "pa_ip"]}
DEFAULT_BETA = {"mvp": [2.0, 0.6, 0.8, 0.8], "cy": [1.6, 0.8, 0.5, -0.9], "roy": [2.0, 0.5]}
FIP_C = 3.10


def _fold(s: str) -> str:
    from oddsmarkets.common import prediction_markets as cpm
    return cpm.fold(str(s))


def _team_league(abbr_to_league: dict, abbr: str) -> str | None:
    return abbr_to_league.get(str(abbr))


def _abbr_league(season: int) -> dict:
    out = {}
    try:
        from oddsmarkets.baseball import canon
        for tid in canon.team_ids():
            a = canon.team_abbr(tid, season)
            if a:
                out[a] = canon.team_league(tid, season)
    except Exception:  # noqa: BLE001
        pass
    return out


def season_table(level: str, season: int, pa: pd.DataFrame | None = None, through: Any = None,
                 use_war: bool = True) -> pd.DataFrame:
    """One row per player-role with the award features (role 'h' hitter / 'p' pitcher), league and team."""
    from oddsmarkets.baseball.models import projections as PJ
    pa = PJ.pa_table(level, season) if pa is None else pa
    if pa is None or not len(pa):
        return pd.DataFrame()
    pa = pa[pa["game_type"] == "R"] if (pa["game_type"] == "R").any() else pa
    if through is not None:
        pa = pa[pa["game_date"] < str(through)[:10]]
    lgm = _abbr_league(season)
    bat_team = np.where(pa["top"], pa["away_team"], pa["home_team"])
    fld_team = np.where(pa["top"], pa["home_team"], pa["away_team"])
    # team win % from game results in the PA table (final score per game)
    last = pa.sort_values(["game_pk", "ab"]).groupby("game_pk").tail(1)
    fin = pa.groupby("game_pk").agg(home=("home_team", "first"), away=("away_team", "first"))
    sc = pa.assign(bt=bat_team, end=pa["score_pre"] + pa["runs"]).groupby(["game_pk", "bt"])["end"].max().unstack()
    wins, games = {}, {}
    for gpk, r in fin.iterrows():
        try:
            hs, as_ = sc.loc[gpk, r["home"]], sc.loc[gpk, r["away"]]
        except KeyError:
            continue
        if not (np.isfinite(hs) and np.isfinite(as_)) or hs == as_:
            continue
        w = r["home"] if hs > as_ else r["away"]
        for t in (r["home"], r["away"]):
            games[t] = games.get(t, 0) + 1
        wins[w] = wins.get(w, 0) + 1
    wpct = {t: wins.get(t, 0) / g for t, g in games.items() if g}
    ww = PJ.woba_weights(season)
    rows = []
    # hitters
    d = pd.DataFrame({"pid": pa["batter"], "team": bat_team, "ev": pa["ev"], "wv": pa["woba_value"].fillna(0),
                      "wd": pa["woba_denom"].fillna(0)})
    lg_woba = d["wv"].sum() / max(d["wd"].sum(), 1)
    g = d.groupby("pid").agg(pa=("ev", "size"), hr=("ev", lambda x: int((x == E["HR"]).sum())), wv=("wv", "sum"),
                             wd=("wd", "sum"), team=("team", lambda x: x.value_counts().index[0]))
    g["woba"] = g["wv"] / g["wd"].replace(0, np.nan)
    g["value"] = ((g["woba"] - lg_woba) / 1.20 * g["pa"] + 20.0 * g["pa"] / 600) / 10.0
    for pid, r in g.iterrows():
        rows.append({"pid": str(pid), "role": "h", "team": r["team"], "league": lgm.get(r["team"]), "pa": int(r["pa"]),
                     "hr": int(r["hr"]), "woba": float(r["woba"]) if np.isfinite(r["woba"]) else np.nan, "value": float(r["value"]) if np.isfinite(r["value"]) else 0.0,
                     "team_wpct": wpct.get(r["team"], 0.5)})
    # pitchers
    outs = (pa["outs_post"] - pa["outs"]).clip(0, 3)
    d = pd.DataFrame({"pid": pa["pitcher"], "team": fld_team, "ev": pa["ev"], "outs": outs, "runs": pa["runs"]})
    p = d.groupby("pid").agg(bf=("ev", "size"), k=("ev", lambda x: int((x == E["K"]).sum())),
                             bb=("ev", lambda x: int(x.isin([E["BB"], E["HBP"]]).sum())),
                             hr=("ev", lambda x: int((x == E["HR"]).sum())), outs=("outs", "sum"), runs=("runs", "sum"),
                             team=("team", lambda x: x.value_counts().index[0]))
    p["ip"] = p["outs"] / 3.0
    lg = p.sum(numeric_only=True)
    lg_ra9 = 9 * lg["runs"] / max(lg["ip"], 1)
    raw_fip = (13 * p["hr"] + 3 * p["bb"] - 2 * p["k"]) / p["ip"].replace(0, np.nan)
    lg_raw = (13 * lg["hr"] + 3 * lg["bb"] - 2 * lg["k"]) / max(lg["ip"], 1)
    p["fip"] = raw_fip - lg_raw + lg_ra9
    p["value"] = ((lg_ra9 - p["fip"]) * p["ip"] / 9 + 0.12 * p["ip"] / 9 * 9) / 10.0
    p["ra9"] = 9 * p["runs"] / p["ip"].replace(0, np.nan)
    for pid, r in p.iterrows():
        rows.append({"pid": str(pid), "role": "p", "team": r["team"], "league": lgm.get(r["team"]), "ip": float(r["ip"]),
                     "k": int(r["k"]), "ra9": float(r["ra9"]) if np.isfinite(r["ra9"]) else 9.0,
                     "value": float(r["value"]) if np.isfinite(r["value"]) else 0.0, "team_wpct": wpct.get(r["team"], 0.5)})
    df = pd.DataFrame(rows)
    war = _war_c(level, season) if use_war else None
    if war is not None:
        bat, pit = war
        m = np.where(df["role"] == "h", df["pid"].map(bat), df["pid"].map(pit)).astype(float)
        df["value"] = np.where(np.isfinite(m), m, df["value"])
        df.attrs["value_source"] = "war.py"
    else:
        df.attrs["value_source"] = "proxy"
    return df


def _war_c(level: str, season: int) -> tuple[pd.Series, pd.Series] | None:
    """(batter WAR, pitcher WAR) by pid from builder C's war.for_season (pitchers: mean of the RA9 and expected
    versions), or None."""
    mod = _dio.sibling("war")
    if not mod or not hasattr(mod, "for_season"):
        return None
    try:
        res = mod.for_season(level, season)
    except Exception as exc:  # noqa: BLE001
        logger.info("war.for_season failed: %s", exc)
        return None
    if not isinstance(res, dict) or not res.get("ok"):
        return None
    conv = getattr(mod, "_c_frame", None)
    b = conv(res.get("batters")) if conv else None
    p = conv(res.get("pitchers")) if conv else None
    if b is None or not len(b) or "war" not in b:
        return None
    bat = pd.Series(pd.to_numeric(b["war"], errors="coerce").to_numpy(), index=b["pid"].astype(str))
    pit = pd.Series(dtype=float)
    if p is not None and len(p):
        cols = [c for c in ("war_ra9", "war_x") if c in p]
        if cols:
            pit = pd.Series(p[cols].apply(pd.to_numeric, errors="coerce").mean(axis=1).to_numpy(), index=p["pid"].astype(str))
    return bat, pit


def candidates(tab: pd.DataFrame, award: str, league: str, prior_ids: set | None = None) -> pd.DataFrame:
    """Candidate rows for one league's award with the model's features (z-scored)."""
    if tab is None or not len(tab):
        return pd.DataFrame()
    t = tab[tab["league"] == league]
    h, p = t[t["role"] == "h"].set_index("pid"), t[t["role"] == "p"].set_index("pid")
    if award == "mvp":
        H = h[h["pa"] >= 300]
        P = p[p["ip"] >= 120]
        ids = sorted(set(H.index) | set(P.index))
        rows = []
        for pid in ids:
            v = (H["value"].get(pid, 0.0) if pid in H.index else 0.0) + (P["value"].get(pid, 0.0) if pid in P.index else 0.0)
            hr = H["hr"].get(pid, 0) if pid in H.index else 0
            wo = H["woba"].get(pid, np.nan) if pid in H.index else np.nan
            tm = (H if pid in H.index else P).loc[pid, "team_wpct"]
            rows.append({"pid": pid, "value": v, "hr": hr, "team": tm, "woba": wo})
        df = pd.DataFrame(rows)
        if len(df):
            df["woba"] = df["woba"].fillna(df["woba"].mean())       # pitchers: neutral on the batting feature
    elif award == "cy":
        P = p[p["ip"] >= 40]
        df = pd.DataFrame({"pid": P.index, "value": P["value"].to_numpy(), "k": P["k"].to_numpy(), "ip": P["ip"].to_numpy(),
                           "ra9": P["ra9"].to_numpy()})
    else:
        if prior_ids is None:
            return pd.DataFrame()          # rookie status unknown: no earlier seasons and no debut dates
        H = h[(h["pa"] >= 100) & ~h.index.isin(prior_ids)]
        P = p[(p["ip"] >= 30) & ~p.index.isin(prior_ids)]
        rows = [{"pid": pid, "value": r["value"], "pa_ip": r["pa"] / 600} for pid, r in H.iterrows()]
        rows += [{"pid": pid, "value": r["value"], "pa_ip": r["ip"] / 180} for pid, r in P.iterrows() if pid not in H.index]
        df = pd.DataFrame(rows)
    if not len(df):
        return df
    for f in FEATURES[award]:
        x = df[f].astype(float)
        sd = x.std()
        df["z_" + f] = (x - x.mean()) / (sd if sd and np.isfinite(sd) else 1.0)
    return df.reset_index(drop=True)


def softmax_probs(df: pd.DataFrame, award: str, beta) -> np.ndarray:
    X = df[["z_" + f for f in FEATURES[award]]].to_numpy(float)
    s = X @ np.asarray(beta, float)
    s = s - s.max()
    e = np.exp(s)
    return e / e.sum()


def _prior_ids(level: str, season: int) -> set | None:
    """Players who are not rookies in `season`: seen in an earlier season's pitch table or debuted (people crosswalk)
    before it. None when neither source is informative (no earlier season on disk and no debut dates)."""
    from oddsmarkets.baseball.models import projections as PJ
    ids = set()
    informative = False
    for pid, v in (_dio.people() or {}).items():
        deb = str((v or {}).get("debut") or "")[:4]
        if deb.isdigit():
            informative = True
            if int(deb) < season - 1:
                ids.add(str(pid))
    for s in _dio.pitch_seasons(level):
        if s >= season:
            continue
        h, p = PJ.season_aggregates(level, s)
        # a rookie keeps the status after a short look (130 AB / 50 IP): only substantial samples disqualify
        ids |= set(h.index[h["PA"] >= 150].astype(str)) | set(p.index[p["PA"] >= 200].astype(str))
        informative = informative or s == season - 1
    return ids if informative else None


def resolve_name(name: str, names: dict[str, str]) -> str | None:
    """MLBAM id for a winner's name from {pid: name}."""
    key = _fold(name)
    hit = [pid for pid, n in names.items() if _fold(n) == key]
    if len(hit) == 1:
        return hit[0]
    from oddsmarkets.common import prediction_markets as cpm
    inv = {}
    for pid, n in names.items():
        inv.setdefault(n, []).append(pid)
    inv = {k: v[0] for k, v in inv.items() if len(v) == 1}
    m = cpm.best_match(name, list(inv), floor=0.88)
    return inv[m] if m else None


_VERBS = (r" (singles|doubles|triples|homers|hits a|walks|intentionally|strikes out|called out|grounds|flies|lines|pops|"
          r"reaches|hit by|out on|bunts|sacrifice|grand slam|ground|was hit|is hit|fouls|chopped|chops|loses|swinging)")


def names_from_pitches(level: str, season: int) -> dict:
    """{pid: "First Last"} from the pitch table: pitchers from `player_name` ("Last, First"), batters from the
    play description's leading name (most common prefix before the verb)."""
    import re
    try:
        df = _dio.read_pitches(level, season, ["player_name", "pitcher", "batter", "des", "events"])
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    if not len(df):
        return out
    pn = df.dropna(subset=["player_name"]).drop_duplicates("pitcher")
    for pid, nm in zip(pn["pitcher"], pn["player_name"]):
        nm = str(nm)
        if "," in nm:
            last, first = nm.split(",", 1)
            nm = f"{first.strip()} {last.strip()}"
        out[str(int(pid))] = nm
    d = df[df["events"].notna() & df["des"].notna()][["batter", "des"]]
    rx = re.compile(r"^(.+?)" + _VERBS)
    cand = d["des"].astype(str).str.extract(rx)[0]
    d = d.assign(nm=cand).dropna(subset=["nm"])
    d = d[d["nm"].str.split().str.len().between(2, 4)]
    best = d.groupby("batter")["nm"].agg(lambda x: x.value_counts().index[0])
    for pid, nm in best.items():
        out.setdefault(str(int(pid)), nm)
    return out


def _names(level: str, season: int) -> dict:
    out = names_from_pitches(level, season)
    for pid, v in (_dio.people() or {}).items():
        if (v or {}).get("name"):
            out[str(pid)] = v["name"]
    s = _dio.load_store(level, season)
    for pid, v in (s.get("players") or {}).items():
        if (v or {}).get("name"):
            out[str(pid)] = v["name"]
    return out


def training_rows(level: str = "mlb", seasons=None) -> dict:
    """{award: [(season, league, candidates df, winner row index)]} for the verified winners with data."""
    out = {a: [] for a in WINNERS}
    for s in sorted(seasons or _dio.pitch_seasons(level)):
        if s not in WINNERS["mvp"]:
            continue
        tab = season_table(level, s)
        if not len(tab):
            continue
        names = _names(level, s)
        prior = _prior_ids(level, s)
        for award, by in WINNERS.items():
            for k, lg in enumerate(("AL", "NL")):
                c = candidates(tab, award, lg, prior if award == "roy" else None)
                if not len(c):
                    continue
                pid = resolve_name(by[s][k], {p: names.get(p, "") for p in c["pid"]})
                if pid is None:
                    continue
                i = int(np.flatnonzero(c["pid"].to_numpy() == pid)[0])
                out[award].append((s, lg, c, i))
    return out


def fit(rows: list, award: str, l2: float = 0.5) -> dict:
    """Conditional-logit MLE; defaults when fewer than four league-seasons."""
    if len(rows) < 4:
        return {"beta": DEFAULT_BETA[award], "n": len(rows), "source": "default"}
    Xs = [c[["z_" + f for f in FEATURES[award]]].to_numpy(float) for _, _, c, _ in rows]
    ys = [i for *_, i in rows]

    def nll(b):
        tot = l2 * np.sum((b - np.asarray(DEFAULT_BETA[award])) ** 2)
        for X, i in zip(Xs, ys):
            s = X @ b
            m = s.max()
            tot -= s[i] - m - np.log(np.exp(s - m).sum())
        return tot

    r = minimize(nll, np.asarray(DEFAULT_BETA[award], float), method="BFGS")
    ll = -float(r.fun)
    hits = sum(int(np.argmax(X @ r.x) == i) for X, i in zip(Xs, ys))
    return {"beta": [round(float(x), 4) for x in r.x], "n": len(rows), "source": "fitted", "top1": hits,
            "loglik": round(ll, 3)}


def for_season(level: str, season: int, through: Any = None, markets: dict | None = None, top: int = 15) -> dict:
    """{award_key: {"model": [{pid, name, p, value, ...}], "market": TITLE|None, "fit": {...}}} for the six awards."""
    seasons = [s for s in _dio.pitch_seasons(level) if s < season]
    train = training_rows(level, seasons)
    fits = {a: fit(train[a], a) for a in WINNERS}
    tab = season_table(level, season, through=through)
    names = _names(level, season)
    prior = _prior_ids(level, season)
    out: dict[str, Any] = {"season": season, "verified_winners": VERIFIED, "source": SOURCE,
                           "value_source": tab.attrs.get("value_source") if len(tab) else None}
    for award in WINNERS:
        for lg in ("AL", "NL"):
            key = f"{lg.lower()}_{award}"
            c = candidates(tab, award, lg, prior if award == "roy" else None)
            rec: dict[str, Any] = {"fit": fits[award]}
            if len(c):
                p = softmax_probs(c, award, fits[award]["beta"])
                c = c.assign(p=p).sort_values("p", ascending=False).head(top)
                rec["model"] = [{"pid": r["pid"], "name": names.get(r["pid"]), "p": round(float(r["p"]), 5),
                                 "value": round(float(r["value"]), 2)} for _, r in c.iterrows()]
            else:
                rec["model"] = []
                rec["reason"] = ("rookie status unknown (no earlier season on disk and no debut dates)" if award == "roy"
                                 else "no candidates")
            mk = (markets or {}).get(key)
            if mk:
                rec["market"] = {k: mk.get(k) for k in ("available", "reason", "probs", "markets")}
                byname = {_fold(n or ""): r["pid"] for r in rec["model"] for n in [r["name"]]}
                cmp = []
                for mid, q in (mk.get("probs") or {}).items():
                    pid = mid if not str(mid).startswith("name:") else byname.get(str(mid)[5:])
                    mp = next((r["p"] for r in rec["model"] if r["pid"] == pid), None)
                    cmp.append({"id": mid, "pid": pid, "market": q, "model": mp})
                rec["vs_market"] = sorted(cmp, key=lambda r: -(r["market"] or 0))[:top]
            out[key] = rec
    return out
