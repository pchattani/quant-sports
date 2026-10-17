"""
Valuation v2 (docs/VALUE_SECTIONS.md section 4): a player's projected multi-season value, its uncertainty, position
scarcity, and the draft-pick value curve the trade ratings use. Payload: valuation.json (PAYLOADS.md "As built").

The currency is the value page's: points (EPA) per game above a replacement-level player at the same position
(value.py, GVAR). Everything below is fitted on our own value tables (data/<S>/value.json, every completed season
since 1999) -- no salary, contract or third-party valuation enters.

Current level (talent now)
--------------------------
x_eff = the games-weighted mean of this season's and last season's GVAR per game (last season's games count half);
theta_0 = mu_pos(age) + r (x_eff - mu_pos(age)), r = g_eff / (g_eff + k_pos), g_eff the weighted games. k_pos is the
position's shrinkage constant, read off the season-to-season regression slope b at the typical full-season sample g
(b = g / (g + k), so k = g (1 - b) / b): a quarterback's per-game value is about half signal in a full season (k ~ 14
games), a cornerback's a quarter (k ~ 40). Quarterbacks with a team-strength QB value use the QB model instead
(models/team_strength.py: EPA per dropback above an average QB, the season simulation's QB input, already shrunk):
theta_0 = np x (qb_val - qb_new), np the league's dropbacks per game and qb_new the model's value for an unknown QB,
which is what a freely available QB is.

Ageing
------
The season-to-season regression next = a + b x + c1 A + c2 A^2 (A = age - 27, weighted by the smaller of the two
seasons' games, players with 4+ games in both) gives the expected change in talent from age A to A + 1 for an average
player: delta(A) = a + (b - 1) mean + c1 A + c2 A^2. Talent k seasons ahead: theta_k = theta_0 + sum of delta over
the ages passed. The QB model's own carry-over (0.95 a season, toward an average QB) is applied to QB-model levels.

Availability
------------
Expected games in season k = 17 x (chance he is still playing, from the share of players of that position and age
band with 4+ games who appear the next season) x (the games share of those who do). The rest of the current season
uses the remaining games, scaled by his roster status (injured reserve: none of the next four games).

Uncertainty
-----------
sigma_1 = the residual SD of the season-ahead regression; sigma_2 the same two seasons ahead; the drift per season is
sqrt(sigma_2^2 - sigma_1^2). 400 draws per player of a random walk (theta_0 + N(0, sigma_1) + drift per season), each
season's value floored at 0 (a team can always field a replacement player), give the 10th-90th percentile band.

Value
-----
value = sum over the rest of this season and the next H = 3 seasons of 0.9^k x max(0, theta_k) x E[games_k], in points
above replacement; wins = value x k_resp x wins per point of season margin (fitted from the schedules' results).

Position scarcity
-----------------
Per position, the marginal starter is the (32 x slots)-th best projected next-season level in the league (rostered or
not); "over the marginal starter" is a player's next-season level above it. The position's scarcity index is the
spread between its top-five level and its marginal starter, relative to the average position's spread.

Draft-pick value curve
----------------------
For drafts 2008 onward (draft slots from nflverse's players release, which takes them from the NFL's own draft API
from 2008; earlier slots there are scraped from Pro Football Reference, whose terms forbid that use, so they are left
out), each pick's realised value = sum over the drafted player's first four seasons of 0.9^k x max(0, GVAR) (zero in
seasons he did not play). Offensive linemen and long snappers are excluded (we cannot value them, not because their
picks are worth nothing): the curve is "a pick spent on a position we value". The pick means are fitted with
value(p) = c + a exp(-b (p - 1)); a pick whose slot is unknown (a future pick) is valued at its round's mean.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from oddsmarkets.nfl import analytics as an

logger = logging.getLogger(__name__)

VERSION = "valuation-2"
H = 3                       # seasons after the current one
DISCOUNT = 0.9
N_DRAWS = 400
AGE0 = 27.0
SEASON_GAMES = 17
PREV_W = 0.5                # last season's games count half in the current level
POS = ("QB", "RB", "WR", "TE", "EDGE", "DL", "LB", "CB", "S", "K", "P")
ROSTERED = ("ACT", "INA", "RES", "PUP", "SUS", "EXE", "NWT")
SLOTS = {"QB": 1, "RB": 2, "WR": 3, "TE": 2, "EDGE": 2, "DL": 2, "LB": 2, "CB": 3, "S": 2, "K": 1, "P": 1}
AGE_BANDS = ((0, 24), (24, 27), (27, 30), (30, 33), (33, 36), (36, 99))
QB_CARRY = 0.95
PICK_SEASONS = 4
NO_VALUE_POS = {"OL", "T", "G", "C", "OT", "OG", "LS", "OC", "IOL"}
FIRST_DRAFT = 2008          # NFL draft-API slots in the nflverse players release
_PANEL: dict[str, Any] = {}


# ---------------------------------------------------------------------------------------------- the history panel

def panel_rows(upto: int, root=None) -> list[dict]:
    """[{pid, season, pos, age, games, tg, x (GVAR per game), q}] from data/<S>/value.json for 1999 <= S < upto
    (completed seasons only), cached per process."""
    root = root or an.data_root()
    key = f"{root}|{upto}"
    if key in _PANEL:
        return _PANEL[key]
    out = []
    for S in range(an.FIRST_SEASON, int(upto)):
        d = an.read_json(root / str(S) / "value.json")
        if not d or not d.get("ok") or not d.get("rows") or d.get("basis_season") not in (None, S):
            continue
        cols = d.get("cols") or []
        ix = {c: i for i, c in enumerate(cols)}
        if not {"pid", "pos", "games", "gvar_pg"} <= set(ix):
            continue
        tg = int(d.get("team_games") or SEASON_GAMES)
        for r in d["rows"]:
            x = an.fnum(r[ix["gvar_pg"]])
            g = an.inum(r[ix["games"]]) or 0
            if x is None or g <= 0:
                continue
            out.append({"pid": r[ix["pid"]], "season": S, "pos": r[ix["pos"]], "age": an.fnum(r[ix["age"]]) if "age" in ix else None,
                        "games": g, "tg": tg, "x": x, "q": bool(r[ix["q"]]) if "q" in ix else True,
                        "name": r[ix["name"]] if "name" in ix else None, "team": r[ix["team"]] if "team" in ix else None})
    _PANEL[key] = out
    return out


def reset() -> None:
    _PANEL.clear()


def _wls(X: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    sw = np.sqrt(w)
    return np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)[0]


def fit_curves(rows: list[dict], min_games: int = 4) -> dict:
    """Per position: {"a", "b", "c1", "c2", "mean", "k", "g_typ", "sd1", "sd2", "drift", "n", "ret": [[lo, hi, p_ret,
    share]], "mu": {age: level}} from consecutive seasons of the panel (see the module docstring)."""
    by = {}
    for r in rows:
        by[(r["pid"], r["season"])] = r
    out: dict[str, dict] = {}
    for pos in POS:
        mem = [r for r in rows if r["pos"] == pos]
        pairs, pairs2, ret_rows = [], [], []
        for r in mem:
            if r["games"] < min_games:
                continue
            n1 = by.get((r["pid"], r["season"] + 1))
            ret_rows.append((r.get("age"), r["x"], n1))
            if n1 is not None and n1["games"] >= min_games and n1["pos"] == pos and r.get("age") is not None:
                pairs.append((r["x"], n1["x"], r["age"] - AGE0, min(r["games"], n1["games"]), r["games"]))
            n2 = by.get((r["pid"], r["season"] + 2))
            if n2 is not None and n2["games"] >= min_games and n2["pos"] == pos and r.get("age") is not None:
                pairs2.append((r["x"], n2["x"], r["age"] - AGE0, min(r["games"], n2["games"])))
        if len(pairs) < 30:
            continue
        P = np.asarray(pairs, float)
        x, y, A, w, g = P[:, 0], P[:, 1], P[:, 2], P[:, 3], P[:, 4]
        X = np.c_[np.ones(len(x)), x, A, A * A]
        a, b, c1, c2 = (float(v) for v in _wls(X, y, w))
        b = min(max(b, 0.05), 0.95)
        res = y - X @ np.array([a, b, c1, c2])
        sd1 = float(np.sqrt(np.average(res ** 2, weights=w)))
        mean = float(np.average(x, weights=w))
        g_typ = float(np.median(g))
        k = g_typ * (1.0 - b) / b
        sd2 = sd1
        if len(pairs2) >= 30:
            Q = np.asarray(pairs2, float)
            # two seasons ahead: the one-step model applied twice (talent persists; ageing for two years)
            pred = a + b * Q[:, 0] + c1 * Q[:, 2] + c2 * Q[:, 2] ** 2
            pred = pred + (a + (b - 1.0) * mean + c1 * (Q[:, 2] + 1) + c2 * (Q[:, 2] + 1) ** 2)
            sd2 = max(sd1, float(np.sqrt(np.average((Q[:, 1] - pred) ** 2, weights=Q[:, 3]))))
        med = float(np.median([r["x"] for r in mem if r["games"] >= min_games])) if mem else 0.0
        rets = {}
        for lvl in ("lo", "hi"):
            ret = []
            for lo, hi in AGE_BANDS:
                band = [n1 for age, x0, n1 in ret_rows if age is not None and lo <= age < hi and ((x0 >= med) == (lvl == "hi"))]
                if len(band) < 10:
                    ret.append([lo, hi, None, None])
                    continue
                back = [n1 for n1 in band if n1 is not None]
                share = float(np.mean([min(1.0, n1["games"] / max(n1["tg"], 1)) for n1 in back])) if back else 0.5
                ret.append([lo, hi, round(len(back) / len(band), 4), round(share, 4)])
            for i, rr in enumerate(ret):                         # fill gaps from the neighbours
                if rr[2] is None:
                    nb = [q for q in ret if q[2] is not None]
                    rr[2], rr[3] = (nb[min(len(nb) - 1, i)][2], nb[min(len(nb) - 1, i)][3]) if nb else (0.7, 0.6)
            rets[lvl] = ret
        out[pos] = {"a": round(a, 5), "b": round(b, 4), "c1": round(c1, 6), "c2": round(c2, 7), "mean": round(mean, 4),
                    "k": round(k, 2), "g_typ": g_typ, "sd1": round(sd1, 4), "sd2": round(sd2, 4),
                    "drift": round(math.sqrt(max(0.0, sd2 ** 2 - sd1 ** 2)), 4), "n": len(pairs), "n2": len(pairs2), "ret": rets["hi"],
                    "ret_lo": rets["lo"], "med": round(med, 4)}
    return out


def delta(c: dict, age: float | None) -> float:
    """Expected change in talent (points per game) from age to age + 1 for an average player at the position."""
    if not c or age is None:
        return 0.0
    A = float(age) - AGE0
    A = max(-6.0, min(12.0, A))
    return float(c["a"] + (c["b"] - 1.0) * c["mean"] + c["c1"] * A + c["c2"] * A * A)


def mu_at(c: dict, age: float | None) -> float:
    """The position's mean level (the regression target); ageing enters through delta()."""
    return float(c.get("mean", 0.0)) if c else 0.0


def ret_at(c: dict, age: float | None, level: float | None = None) -> tuple[float, float]:
    """(chance he plays the next season, games share when he does) for the position, age band and level (above or
    below the position's median per-game value: better players keep their jobs)."""
    if not c or not c.get("ret"):
        return 0.75, 0.6
    tab = c["ret"] if (level is None or level >= float(c.get("med", 0.0)) or not c.get("ret_lo")) else c["ret_lo"]
    a = 27.0 if age is None else float(age)
    for lo, hi, p, s in tab:
        if lo <= a < hi:
            return float(p), float(s)
    return float(tab[-1][2]), float(tab[-1][3])


def current_level(c: dict, x_cur: float | None, g_cur: float, x_prev: float | None, g_prev: float, age: float | None,
                  x_prev2: float | None = None, g_prev2: float = 0.0) -> tuple[float | None, float]:
    """(theta_0, r): the shrunk current level from this season and the last two (last season's games count PREV_W,
    the season before PREV_W squared)."""
    if not c:
        return None, 0.0
    num, den = 0.0, 0.0
    if x_cur is not None and g_cur > 0:
        num += x_cur * g_cur
        den += g_cur
    if x_prev is not None and g_prev > 0:
        num += x_prev * g_prev * PREV_W
        den += g_prev * PREV_W
    if x_prev2 is not None and g_prev2 > 0:
        num += x_prev2 * g_prev2 * PREV_W ** 2
        den += g_prev2 * PREV_W ** 2
    if den <= 0:
        return None, 0.0
    x_eff = num / den
    r = den / (den + float(c["k"]))
    m = mu_at(c, age)
    return m + r * (x_eff - m), r


def project(c: dict, theta0: float, age: float | None, remaining: float, avail_now: float = 1.0, h: int = H,
            qb_model: bool = False, sd_post: float | None = None, rng: np.random.Generator | None = None,
            qb_target: float = 0.0, own_share: tuple[float, float] | None = None) -> dict:
    """Seasons 0 (the rest of the current season, `remaining` games) .. h: level, expected games, value; the
    discounted total, its 10th-90th percentile band and the per-season band."""
    levels, games = [], []
    lv = theta0
    p_alive = 1.0
    for k in range(h + 1):
        a_k = None if age is None else age + k
        if k == 0:
            g = remaining * avail_now
        else:
            lv = lv + delta(c, None if age is None else age + k - 1)
            if qb_model:
                # the QB model carries a QB's value toward an average QB (0.95 a season); qb_target is that level
                lv = qb_target + QB_CARRY * (lv - qb_target)
            p, sh = ret_at(c, None if a_k is None else a_k - 1, lv)
            if own_share is not None:
                # his own games share (games / club games over this season and last), shrunk toward the table's
                g_own, tg_own = own_share
                sh = (g_own + SEASON_GAMES * sh) / (tg_own + SEASON_GAMES)
            p_alive *= p
            g = SEASON_GAMES * p_alive * sh
        levels.append(lv)
        games.append(g)
    disc = np.array([DISCOUNT ** k for k in range(h + 1)])
    L, G = np.array(levels), np.array(games)
    total = float(np.sum(disc * np.maximum(L, 0.0) * G))
    s1 = float(c.get("sd1", 0.5)) if sd_post is None else float(sd_post)
    dr = float(c.get("drift", 0.0))
    rng = rng or np.random.default_rng(7)
    z = rng.standard_normal((N_DRAWS, h + 1))
    walk = np.cumsum(np.c_[z[:, :1] * s1, z[:, 1:] * dr], axis=1)
    draws = np.maximum(L[None, :] + walk, 0.0)
    tot = draws @ (disc * G)
    lo, hi = (float(x) for x in np.percentile(tot, [10, 90]))
    plo, phi = np.percentile(L[None, :] + walk, [10, 90], axis=0)
    return {"levels": levels, "games": games, "total": total, "lo": lo, "hi": hi, "lv_lo": [float(x) for x in plo],
            "lv_hi": [float(x) for x in phi]}


# ---------------------------------------------------------------------------------------------- wins per point

_WPP: dict[str, float] = {}


def wins_per_point() -> float:
    """Wins per point of season scoring margin: the slope of regular-season wins on points for minus against, team
    seasons 2002-2025 from the schedules (about 1/36); 0.0278 when the schedules are not on disk."""
    if "v" in _WPP:
        return _WPP["v"]
    v = 0.0278
    try:
        from oddsmarkets.nfl.analytics.context import load_release
        df = load_release("schedules", None, ["season", "game_type", "home_team", "away_team", "home_score", "away_score"])
        if df is not None and len(df):
            df = df[(df["game_type"] == "REG") & df["home_score"].notna() & (df["season"] >= 2002) & (df["season"] <= 2025)]
            import pandas as pd
            h = pd.DataFrame({"season": df["season"], "team": df["home_team"], "m": df["home_score"] - df["away_score"]})
            a = pd.DataFrame({"season": df["season"], "team": df["away_team"], "m": df["away_score"] - df["home_score"]})
            t = pd.concat([h, a])
            t["w"] = (t["m"] > 0).astype(float) + 0.5 * (t["m"] == 0)
            s = t.groupby(["season", "team"]).agg(m=("m", "sum"), w=("w", "sum"))
            X = np.c_[np.ones(len(s)), s["m"].to_numpy(float)]
            v = float(np.linalg.lstsq(X, s["w"].to_numpy(float), rcond=None)[0][1])
    except Exception as exc:                                     # noqa: BLE001
        logger.info("wins per point: %s", exc)
    _WPP["v"] = v
    return v


# ---------------------------------------------------------------------------------------------- the pick curve

def pick_curve(rows: list[dict], draft: dict[str, dict], last_season: int, first: int = FIRST_DRAFT) -> dict:
    """{"picks": [value of overall pick 1..262], "rounds": {r: mean}, "a", "b", "c", "n", "drafts": [first, last],
    "means": [[pick bin centre, mean, n]]}: realised discounted value over a drafted player's first four seasons.
    `draft` = {pid: {"year", "round", "pick", "pos"}}."""
    val: dict[tuple, float] = {}
    for r in rows:
        val[(r["pid"], r["season"])] = max(0.0, r["x"]) * r["games"]
    last_draft = last_season - PICK_SEASONS + 1
    pts = []
    for pid, d in draft.items():
        y, p = an.inum(d.get("year")), an.inum(d.get("pick"))
        if y is None or p is None or y < first or y > last_draft or p < 1:
            continue
        if str(d.get("pos") or "").upper() in NO_VALUE_POS:
            continue
        v = sum(DISCOUNT ** k * val.get((pid, y + k), 0.0) for k in range(PICK_SEASONS))
        pts.append((p, v, an.inum(d.get("round"))))
    if len(pts) < 200:
        return {"ok": False, "reason": f"{len(pts)} drafted players with a value history (need 200)"}
    P = np.asarray([(p, v) for p, v, _ in pts], float)
    # binned means (8 picks a bin), then c + a exp(-b (p - 1)) by a grid over b and least squares for a, c
    bins = np.arange(1, 266, 8)
    means = []
    for lo in bins:
        m = P[(P[:, 0] >= lo) & (P[:, 0] < lo + 8)]
        if len(m) >= 5:
            means.append([float(lo + 3.5), float(m[:, 1].mean()), int(len(m))])
    M = np.asarray(means, float)
    best = None
    for b in np.linspace(0.002, 0.08, 157):
        X = np.c_[np.ones(len(M)), np.exp(-b * (M[:, 0] - 1))]
        coef = _wls(X, M[:, 1], M[:, 2])
        err = float(np.sum(M[:, 2] * (M[:, 1] - X @ coef) ** 2))
        if best is None or err < best[0]:
            best = (err, b, coef)
    _, b, (c, a) = best
    picks = [max(0.0, float(c + a * math.exp(-b * (p - 1)))) for p in range(1, 263)]
    rounds = {}
    for rd in range(1, 8):
        lo, hi = 32 * (rd - 1) + 1, 32 * rd
        rounds[str(rd)] = round(float(np.mean(picks[lo - 1:hi])), 2)
    return {"ok": True, "picks": [round(x, 2) for x in picks], "rounds": rounds, "a": round(float(a), 4), "b": round(float(b), 5),
            "c": round(float(c), 4), "n": len(pts), "drafts": [first, last_draft], "seasons": PICK_SEASONS, "discount": DISCOUNT,
            "means": [[round(x, 1), round(y, 2), int(n)] for x, y, n in means],
            "note": "Realised value over a drafted player's first four seasons (points above replacement, discounted 10% a "
                    "season, seasons below replacement count zero), offensive linemen and long snappers excluded; picks "
                    f"from the {first}-{last_draft} drafts. Draft slots: the NFL's draft data via nflverse's players release "
                    f"(from {FIRST_DRAFT}; earlier slots there come from Pro Football Reference, whose terms forbid this use)."}


def pick_value(curve: dict | None, year: int, rnd_: int | None, pick: int | None, as_of_season: int, conditional: bool = False) -> float | None:
    """Value at as_of_season of a pick in the `year` draft: the curve at its slot (its round's mean when the slot is
    unknown), discounted for the seasons until it is used; conditional picks count half."""
    if not curve or not curve.get("ok"):
        return None
    if pick:
        v = curve["picks"][max(1, min(262, int(pick))) - 1]
    elif rnd_:
        v = (curve.get("rounds") or {}).get(str(int(rnd_)))
        if v is None:
            return None
    else:
        return None
    wait = max(0, int(year) - int(as_of_season) - 1)
    v = float(v) * DISCOUNT ** wait
    return v * (0.5 if conditional else 1.0)


def draft_table() -> dict[str, dict]:
    """{gsis_id: {"year", "round", "pick", "pos", "team"}} from the people table (nflverse players release) for drafts
    from FIRST_DRAFT on (the NFL draft API's slots)."""
    from oddsmarkets.nfl.analytics import people
    out = {}
    for pid, p in people.people().items():
        d = p.get("draft") or {}
        y = an.inum(d.get("year"))
        if y is None or y < FIRST_DRAFT or not d.get("pick"):
            continue
        out[pid] = {"year": y, "round": an.inum(d.get("round")), "pick": an.inum(d.get("pick")), "pos": p.get("pos"), "team": d.get("team")}
    return out


# ---------------------------------------------------------------------------------------------- the payload

COLS = ["pid", "name", "team", "pos", "age", "status", "lvl", "r", "proj", "games", "value", "lo", "hi", "wins", "over_ms", "now_pg", "src"]


def build(season: int, recs: dict[str, dict], qbs: dict[str, float] | None, np_lg: float, qb_new: float, remaining: dict[str, int],
          k_resp: float, prev_recs: dict[str, dict] | None = None, unsigned: list[dict] | None = None, root=None,
          rows: list[dict] | None = None, wpp: float | None = None, draft: dict | None = None, curve: dict | None = None,
          tg_cur: int | None = None, roster: dict[str, dict] | None = None) -> dict:
    """valuation.json for the current season: per player (current rosters, plus unsigned players with value) the
    current level, the projected level and expected games for the rest of this season and the next H seasons, the
    discounted value with its band, wins, and value over the position's marginal starter; the fitted curves (ageing,
    availability, uncertainty), the scarcity table and the draft-pick value curve."""
    rows = rows if rows is not None else panel_rows(season, root)
    curves = fit_curves(rows)
    wpp = wpp if wpp is not None else wins_per_point()
    if curve is None:
        try:
            curve = pick_curve(rows, draft if draft is not None else draft_table(), season - 1)
        except Exception as exc:                                 # noqa: BLE001
            logger.info("pick curve: %s", exc)
            curve = {"ok": False, "reason": str(exc)}
    prev_recs = prev_recs or {}
    rng = np.random.default_rng(20261016)
    out_rows, levels_next = [], {}
    rows_by = {(r["pid"], r["season"]): r for r in rows}
    cand = dict(recs)
    for u in unsigned or []:
        cand.setdefault(u["pid"], {**u, "team": None, "status": "FA"})
    # players on a current roster without a game this season (injured, backups, new arrivals): last two seasons' form
    for pid, ro in (roster or {}).items():
        if pid in cand or ro.get("status") not in ROSTERED or not ro.get("team"):
            continue
        pr = prev_recs.get(pid) or {}
        p1, p2 = rows_by.get((pid, season - 1)), rows_by.get((pid, season - 2))
        if not pr and not p1 and not p2 and not (str(ro.get("pos") or "").upper() == "QB" and (qbs or {}).get(pid) is not None):
            continue
        base = pr or p1 or p2 or {}
        pos = pr.get("pos") or (p1 or p2 or {}).get("pos") or ("QB" if str(ro.get("pos") or "").upper() == "QB" else None)
        if pos is None:
            continue
        age = an.fnum(pr.get("age")) + 1.0 if pr and an.fnum(pr.get("age")) is not None else None
        if age is None and (p1 or p2):
            a0 = (p1 or p2).get("age")
            age = None if a0 is None else a0 + (1 if p1 else 2)
        cand[pid] = {"pid": pid, "name": base.get("name") or pid, "team": ro.get("team"), "pos": pos, "age": age, "games": 0,
                     "gvar_pg": None, "status": ro.get("status"), "src": season}
    for pid, rc in cand.items():
        pos = rc.get("pos")
        c = curves.get(pos)
        if not c:
            continue
        team = rc.get("team")
        if not team and rc.get("status") != "FA":
            continue
        g_cur = float(rc.get("games") or 0) if rc.get("src", season) == season else 0.0
        x_cur = rc.get("gvar_pg") if g_cur else None
        pr = prev_recs.get(pid) or {}
        if not pr and (pid, season - 1) in rows_by:
            p1 = rows_by[(pid, season - 1)]
            pr = {"gvar_pg": p1["x"], "games": p1["games"]}
        x_prev, g_prev = pr.get("gvar_pg"), float(pr.get("games") or 0)
        p2 = rows_by.get((pid, season - 2))
        x_prev2, g_prev2 = (p2["x"], float(p2["games"])) if p2 else (None, 0.0)
        if rc.get("src") == season - 1:
            x_prev, g_prev = rc.get("gvar_pg"), float(rc.get("games") or 0)
            x_prev2, g_prev2 = (p2["x"], float(p2["games"])) if p2 else (None, 0.0)
        age = an.fnum(rc.get("age"))
        if age is not None and rc.get("src") == season - 1:
            age += 1.0
        qbm = pos == "QB" and (qbs or {}).get(pid) is not None
        if qbm:
            theta0 = np_lg * (float(qbs[pid]) - qb_new)
            r = None
            src = "qb"
        else:
            theta0, r = current_level(c, x_cur, g_cur, x_prev, g_prev, age, x_prev2, g_prev2)
            src = "gvar"
        if theta0 is None:
            continue
        st = rc.get("status")
        # his own availability: games over club games this season and last, shrunk toward 0.9 with 8 games
        g_own = g_cur + g_prev
        tg_own = (float(tg_cur) if (tg_cur and g_cur) else g_cur) + (SEASON_GAMES if g_prev else 0.0)
        tg_own = max(tg_own, g_own)
        own = (g_own + 8 * 0.9) / (tg_own + 8)
        avail = {"RES": 0.0, "PUP": 0.2, "SUS": 0.3, "FA": 0.0}.get(st, own if st != "INA" else 0.95 * own)
        rem = float(remaining.get(team, 0) if team else 0)
        if st == "RES" and rem > 4:
            avail = 0.45 * own * (rem - 4) / rem
        sd_post = None if r is None else max(0.05, float(c["sd1"]) * math.sqrt(max(0.15, 1.0 - 0.5 * r)))
        pj = project(c, theta0, age, rem, avail, H, qb_model=qbm, sd_post=sd_post, rng=rng, qb_target=np_lg * (0.0 - qb_new),
                     own_share=(g_own, tg_own) if tg_own > 0 else None)
        levels_next[pid] = (pos, pj["levels"][1])
        out_rows.append({"pid": pid, "name": rc.get("name"), "team": team, "pos": pos, "age": an.rnd(age, 1), "status": st,
                         "lvl": an.rnd(theta0, 2), "r": an.rnd(r, 2), "proj": [an.rnd(x, 2) for x in pj["levels"]],
                         "games": [an.rnd(x, 1) for x in pj["games"]], "value": an.rnd(pj["total"], 1), "lo": an.rnd(pj["lo"], 1),
                         "hi": an.rnd(pj["hi"], 1), "wins": an.rnd(pj["total"] * k_resp * wpp, 2),
                         "now_pg": an.rnd(rc.get("gvar_pg"), 2) if g_cur else None, "src": src})
    # scarcity: the marginal starter per position (next season's levels, everyone with a projection)
    scar, spread = {}, {}
    for pos in POS:
        lv = sorted((v for p, (ps, v) in levels_next.items() if ps == pos), reverse=True)
        n = 32 * SLOTS[pos]
        if len(lv) <= n:
            continue
        ms = lv[n - 1]
        top = float(np.mean(lv[:5]))
        scar[pos] = {"marginal": round(ms, 3), "top5": round(top, 3), "starters": n, "spread": round(top - ms, 3)}
        spread[pos] = top - ms
    avg = float(np.mean(list(spread.values()))) if spread else 1.0
    for pos, v in scar.items():
        v["index"] = round(spread[pos] / avg, 2) if avg > 0 else None
    for r in out_rows:
        s = scar.get(r["pos"])
        r["over_ms"] = an.rnd(r["proj"][1] - s["marginal"], 2) if s and r["proj"][1] is not None else None
    out_rows.sort(key=lambda r: -(r["value"] or 0))
    pub_curves = {p: {k: v for k, v in c.items() if k in ("b", "k", "sd1", "sd2", "drift", "n", "ret", "mean")} | {
        "ageing": [[a, round(delta(c, a), 3)] for a in range(21, 38)]} for p, c in curves.items()}
    return {"ok": True, "season": season, "updated_at": an.now(), "version": VERSION, "horizon": H, "discount": DISCOUNT,
            "k_resp": round(k_resp, 4), "wins_per_point": round(wpp, 5), "np": round(np_lg, 2), "qb_new": qb_new, "qb_carry": QB_CARRY,
            "cols": COLS, "rows": [[r.get(c) for c in COLS] for r in out_rows], "curves": pub_curves, "scarcity": scar,
            "pick_curve": curve, "seasons": [season + k for k in range(H + 1)],
            "notes": {"value": "Projected points above a replacement player over the rest of this season and the next three, "
                               "discounted 10% a season, each season floored at zero; band = 10th-90th percentile.",
                      "qb": "Quarterbacks with a team-strength QB value are projected from it (EPA per dropback above an average "
                            "QB x dropbacks per game, above the model's value for an unknown QB).",
                      "salary": "No salary, cap or contract enters: the only contract source we have (OverTheCap via nflverse) "
                                "does not permit republishing.",
                      "availability": "Expected games from how often players of the position and age play the next season, "
                                      "and how much; injured reserve removes the next four games."},
            "credits": [an.NFLVERSE_CREDIT]}


def as_of(pid: str, pos: str | None, season: int, rows_by: dict[tuple, dict], curves: dict, remaining: float, h: int = H,
          age: float | None = None) -> dict | None:
    """A player's projection as it stood before `season`'s value was known (completed seasons only): the last two
    completed seasons' GVAR per game as the current level. Used for a trade's "value at the time"."""
    p1, p2 = rows_by.get((pid, season - 1)), rows_by.get((pid, season - 2))
    if p1 is None and p2 is None:
        return None
    pos = pos or (p1 or p2)["pos"]
    c = curves.get(pos)
    if not c:
        return None
    x1, g1 = (p1["x"], p1["games"]) if p1 else (None, 0)
    x2, g2 = (p2["x"], p2["games"]) if p2 else (None, 0)
    if age is None:
        a0 = (p1 or p2).get("age")
        age = None if a0 is None else a0 + (1 if p1 else 2)
    theta0, r = current_level(c, x1, float(g1), x2, float(g2), age)
    if theta0 is None:
        return None
    g_own = float(g1 + g2)
    tg_own = float((p1["tg"] if p1 else 0) + (p2["tg"] if p2 else 0))
    own = (g_own + 8 * 0.9) / (tg_own + 8) if tg_own else 0.9
    pj = project(c, theta0, age, remaining, own, h, rng=np.random.default_rng(11), own_share=(g_own, tg_own) if tg_own else None)
    pj["theta0"] = theta0
    pj["pos"] = pos
    return pj
