"""
Enriched stints: builder A's on-ice segments with the season's events attributed to them.

A stint is a stretch of play with an unchanged set of skaters and goalies on both sides. Each event is attributed
to the stint it happened in: a faceoff to the stint that starts at its second (start <= t < end), every other
event to the stint whose players were on the ice when it happened (start < t <= end: a goal at a change belongs to
the players coming off). Per stint and side (h = home, a = away):

    cf, ff, sf, gf  shot attempts (Corsi), unblocked attempts (Fenwick), shots on goal, goals
    xg              summed xG of the unblocked attempts (xg.py)
    *_adj           the same score- and venue-adjusted (McCurdy-style): an event by a side leading by d
                    (clipped to +-3) at venue v gets weight 0.5 / s(d, v), s the league's share of that metric taken
                    by such sides at 5v5 that season (goals take the xG weights)

plus the stint's strength from the home view (`5v5`, `pp_h`, `pp_a`, `ev_other` for 4v4/3v3, `en` when a net is
empty), the zone of a faceoff at its start from the home view (`O`, `D`, `N`; `F` = on the fly), the score
before it (score_h0, score_a0: goals at or before its start) and both teams' back-to-back flags.

`player_long(st)` stacks the stints into one row per player-stint from the player's side (strength `5v5`, `pp`,
`pk`, `ev_other`, `en_for` (own net empty), `en_against`), the input to on-ice rates, lines and RAPM.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _io

VERSION = "nhlstints-2"
METRICS = ["cf", "ff", "sf", "gf", "xg"]
ADJ_CLIP = (0.7, 1.4)
ROLE = {"5v5": ("5v5", "5v5"), "pp_h": ("pp", "pk"), "pp_a": ("pk", "pp"), "ev_other": ("ev_other", "ev_other"),
        "en_h": ("en_for", "en_against"), "en_a": ("en_against", "en_for"), "en": ("en_for", "en_for"), "other": ("other", "other")}


def strength_of(sk_h, sk_a, g_h, g_a) -> np.ndarray:
    sk_h, sk_a = np.asarray(sk_h, float), np.asarray(sk_a, float)
    g_h, g_a = np.asarray(g_h, float), np.asarray(g_a, float)
    both = (g_h == 1) & (g_a == 1)
    out = np.full(len(sk_h), "other", dtype=object)
    out[both & (sk_h == 5) & (sk_a == 5)] = "5v5"
    out[both & (sk_h == sk_a) & (sk_h >= 3) & (sk_h < 5)] = "ev_other"
    out[both & (sk_h > sk_a) & (sk_a >= 3)] = "pp_h"
    out[both & (sk_a > sk_h) & (sk_h >= 3)] = "pp_a"
    out[(g_h == 0) & (g_a == 1)] = "en_h"
    out[(g_a == 0) & (g_h == 1)] = "en_a"
    out[(g_a == 0) & (g_h == 0)] = "en"
    return out


def adjust_weights(ev: pd.DataFrame, xg: np.ndarray) -> dict[str, np.ndarray]:
    """Per-event score/venue weights for cf, ff, sf and xg (gf uses xg) from the season's 5v5 attempts."""
    ih = ev["is_home"].to_numpy(float)
    d_h = np.clip(ev["score_h"].to_numpy(float) - ev["score_a"].to_numpy(float), -3, 3)
    d = np.where(ih == 1, d_h, -d_h)
    five = (ev["sk_h"].to_numpy(float) == 5) & (ev["sk_a"].to_numpy(float) == 5) & (ev["g_h"].to_numpy(float) == 1) \
        & (ev["g_a"].to_numpy(float) == 1)
    t = ev["type"].to_numpy(object)
    masks = {"cf": np.isin(t, _io.ATTEMPTS), "ff": np.isin(t, _io.UNBLOCKED), "sf": np.isin(t, ("goal", "shot-on-goal"))}
    out = {}
    for name, val in [("cf", masks["cf"].astype(float)), ("ff", masks["ff"].astype(float)), ("sf", masks["sf"].astype(float)),
                      ("xg", np.where(np.isfinite(xg), xg, 0.0) * masks["ff"])]:
        w = np.ones(len(ev))
        # league share of the metric taken by the home side at each home score differential
        for k in range(-3, 4):
            m = five & (d_h == k) & np.isfinite(ih)
            tot = float(val[m].sum())
            if tot <= 0:
                continue
            s_home = float(val[m & (ih == 1)].sum()) / tot
            s_home = min(max(s_home, 0.05), 0.95)
            w[(d_h == k) & (ih == 1)] = 0.5 / s_home
            w[(d_h == k) & (ih == 0)] = 0.5 / (1.0 - s_home)
        out[name] = np.clip(w, *ADJ_CLIP)
    out["gf"] = out["xg"]
    del d
    return out


def build(season: int, ev: pd.DataFrame | None = None, sh: pd.DataFrame | None = None) -> pd.DataFrame:
    """The enriched stint table for one season (empty without stints)."""
    from oddsmarkets.nhl.models import xg as xgm
    season = _io.sid(season)
    st = _io.stints_raw(season)
    if not len(st):
        return st
    ev = _io.events(season) if ev is None else ev
    sh = xgm.shot_table(season) if sh is None else sh
    # goalies must not sit in skater slots
    for side, gcol in (("h", "hg"), ("a", "ag")):
        slots = _io.SLOTS_H if side == "h" else _io.SLOTS_A
        g = st[gcol].to_numpy(float)
        for c in slots:
            v = st[c].to_numpy(float)
            st.loc[v == g, c] = np.nan
    st["sk_h"] = np.sum(np.isfinite(st[_io.SLOTS_H].to_numpy(float)), axis=1).astype(float)
    st["sk_a"] = np.sum(np.isfinite(st[_io.SLOTS_A].to_numpy(float)), axis=1).astype(float)
    g_h = np.isfinite(st["hg"].to_numpy(float)).astype(float)
    g_a = np.isfinite(st["ag"].to_numpy(float)).astype(float)
    if not np.isfinite(st["hg"].to_numpy(float)).any():          # no goalie columns: assume both nets manned
        g_h[:] = 1.0
        g_a[:] = 1.0
    st["g_h"], st["g_a"] = g_h, g_a
    gm = _io.back_to_back(_io.games(season, ev))
    gmi = gm.set_index("game_id")
    st["home_team"] = st["game_id"].map(gmi["home"]).to_numpy() if st["home_team"].isna().all() else st["home_team"]
    st["away_team"] = st["game_id"].map(gmi["away"]).to_numpy() if st["away_team"].isna().all() else st["away_team"]
    st["b2b_h"] = st["game_id"].map(gmi["b2b_home"]).fillna(0.0).to_numpy(float)
    st["b2b_a"] = st["game_id"].map(gmi["b2b_away"]).fillna(0.0).to_numpy(float)
    st["strength"] = strength_of(st["sk_h"], st["sk_a"], st["g_h"], st["g_a"])
    if "bad" in st:
        st.loc[st["bad"].to_numpy(float) == 1, "strength"] = "other"     # builder A flagged the shift data

    ugames = np.unique(np.concatenate([st["game_id"].to_numpy(), ev["game_id"].to_numpy()]))
    sc = np.searchsorted(ugames, st["game_id"].to_numpy()).astype(float)
    skey = sc * 1e5 + st["start"].to_numpy(float)
    send = st["end"].to_numpy(float)
    e = ev[(ev["shootout"] == 0) & ev["type"].notna()].reset_index(drop=True)
    e = e.merge(sh[["game_id", "idx", "xg"]], on=["game_id", "idx"], how="left") if len(sh) else e.assign(xg=np.nan)
    ec = np.searchsorted(ugames, e["game_id"].to_numpy()).astype(float)
    ekey = ec * 1e5 + e["sec"].to_numpy(float)
    fo = (e["type"] == "faceoff").to_numpy()
    j = np.where(fo, np.searchsorted(skey, ekey, side="right") - 1, np.searchsorted(skey, ekey, side="left") - 1)
    jj = np.clip(j, 0, len(st) - 1)
    t = e["sec"].to_numpy(float)
    ok = (j >= 0) & (sc[jj] == ec) & np.where(fo, t < send[jj], t <= send[jj])
    xg = e["xg"].to_numpy(float)
    w = adjust_weights(e, xg)
    ty = e["type"].to_numpy(object)
    ih = e["is_home"].to_numpy(float)
    vals = {"cf": np.isin(ty, _io.ATTEMPTS).astype(float), "ff": np.isin(ty, _io.UNBLOCKED).astype(float),
            "sf": np.isin(ty, ("goal", "shot-on-goal")).astype(float), "gf": (ty == "goal").astype(float),
            "xg": np.where(np.isfinite(xg), xg, 0.0) * np.isin(ty, _io.UNBLOCKED)}
    n = len(st)
    cols = {}
    for side, sv in (("h", 1.0), ("a", 0.0)):
        m = ok & (ih == sv)
        for k, v in vals.items():
            cols[f"{side}_{k}"] = np.bincount(jj[m], weights=v[m], minlength=n).astype("float32")
            cols[f"{side}_{k}_adj"] = np.bincount(jj[m], weights=(v * w[k])[m], minlength=n).astype("float32")
    st = pd.concat([st, pd.DataFrame(cols, index=st.index)], axis=1)
    # zone start: a faceoff at the stint's first second
    fm = ok & fo & (np.abs(t - st["start"].to_numpy(float)[jj]) <= 1.0)
    zs = np.full(n, "F", dtype=object)
    z = e["zone"].to_numpy(object)
    zh = np.where(ih == 1, z, np.where(z == "O", "D", np.where(z == "D", "O", z)))
    first = pd.Series(np.flatnonzero(fm)).groupby(jj[fm]).first()
    zs[first.index.to_numpy()] = zh[first.to_numpy()]
    zs = np.where(np.isin(zs.astype(str), ["O", "D", "N", "F"]), zs, "F")
    st["zs_h"] = zs
    # score before the stint
    goal = (ty == "goal") & np.isfinite(ih)
    for side, sv in (("h", 1.0), ("a", 0.0)):
        gk = np.sort(ekey[goal & (ih == sv)])
        st[f"score_{side}0"] = (np.searchsorted(gk, skey, side="right") - np.searchsorted(gk, sc * 1e5 - 0.5, side="left")).astype(float)
    st.attrs["unattributed"] = int((~ok & np.isin(ty, _io.ATTEMPTS)).sum())
    return st


def for_season(season: int, use_cache: bool = True) -> pd.DataFrame:
    from oddsmarkets.nhl.models import xg as xgm
    season = _io.sid(season)
    f = xgm.current_fit() or {}
    key = _io.file_key(_io.events_path(season), _io.stints_path(season), _io.store_path(season), VERSION, f.get("key"),
                       f.get("platt"))
    return _io.cached_frame("stints", str(season), key, lambda: build(season), use_cache)


def player_long(st: pd.DataFrame, strengths: tuple[str, ...] | None = None, metrics: tuple[str, ...] = tuple(METRICS),
                adj: bool = True) -> pd.DataFrame:
    """One row per player-stint, from the player's side: player, team, opp, game_id, start, dur, is_home, role
    (5v5/pp/pk/ev_other/en_for/en_against/other), zs (O/D/N/F own view), score_d0 (own lead at the start),
    for/against counts of `metrics` (cf, ca, ff, fa, sf, sa, gf, ga, xgf, xga, and *_adj when `adj`).
    Compact: float32 counts, categorical strings, only the rows of the requested strengths."""
    if st is None or not len(st):
        return pd.DataFrame()
    parts = []
    stg = st["strength"].to_numpy(object)
    for side in ("h", "a"):
        o = "a" if side == "h" else "h"
        slots = _io.SLOTS_H if side == "h" else _io.SLOTS_A
        role = np.array([ROLE.get(s, ("other", "other"))[0 if side == "h" else 1] for s in stg], dtype=object)
        keep = np.ones(len(st), bool) if strengths is None else np.isin(role, list(strengths))
        if not keep.any():
            continue
        zs = st["zs_h"].to_numpy(object)
        if side == "a":
            zs = np.where(zs == "O", "D", np.where(zs == "D", "O", zs))
        base = {"game_id": st["game_id"].to_numpy()[keep], "start": st["start"].to_numpy(float)[keep],
                "dur": st["dur"].to_numpy(np.float32)[keep],
                "team": st["home_team" if side == "h" else "away_team"].to_numpy(object)[keep],
                "opp": st["away_team" if side == "h" else "home_team"].to_numpy(object)[keep],
                "is_home": np.full(int(keep.sum()), 1.0 if side == "h" else 0.0, dtype=np.float32), "role": role[keep],
                "zs": zs[keep], "score_d0": (st[f"score_{side}0"] - st[f"score_{o}0"]).to_numpy(np.float32)[keep]}
        for k in metrics:
            fk, ak = ("xgf", "xga") if k == "xg" else (f"{k[0]}f", f"{k[0]}a")
            base[fk] = st[f"{side}_{k}"].to_numpy(np.float32)[keep]
            base[ak] = st[f"{o}_{k}"].to_numpy(np.float32)[keep]
            if adj:
                base[fk + "_adj"] = st[f"{side}_{k}_adj"].to_numpy(np.float32)[keep]
                base[ak + "_adj"] = st[f"{o}_{k}_adj"].to_numpy(np.float32)[keep]
        for c in slots:
            p = st[c].to_numpy(float)[keep]
            m = np.isfinite(p)
            if not m.any():
                continue
            d = {k: v[m] for k, v in base.items()}
            d["player"] = p[m]
            parts.append(pd.DataFrame(d))
        del base
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    del parts
    for c in ("team", "opp", "role", "zs"):
        out[c] = out[c].astype("category")
    return out


def player_sums(st: pd.DataFrame, by: tuple[str, ...] = ("game_id", "team", "role"),
                strengths: tuple[str, ...] | None = None, metrics: tuple[str, ...] = tuple(METRICS),
                adj: bool = True) -> pd.DataFrame:
    """Sums of player_long's numeric columns (dur, oz / dz zone starts, for / against counts) grouped by
    (player, *by), aggregated one side-slot at a time so the 10-rows-per-stint long table never exists in full."""
    if st is None or not len(st):
        return pd.DataFrame()
    parts = []
    stg = st["strength"].to_numpy(object)
    keys = ["player", *by]
    for side in ("h", "a"):
        o = "a" if side == "h" else "h"
        role = np.array([ROLE.get(s, ("other", "other"))[0 if side == "h" else 1] for s in stg], dtype=object)
        keep = np.ones(len(st), bool) if strengths is None else np.isin(role, list(strengths))
        zs = st["zs_h"].to_numpy(object)
        if side == "a":
            zs = np.where(zs == "O", "D", np.where(zs == "D", "O", zs))
        cols = {"game_id": st["game_id"].to_numpy(), "team": st["home_team" if side == "h" else "away_team"].to_numpy(object),
                "opp": st["away_team" if side == "h" else "home_team"].to_numpy(object), "role": role,
                "dur": st["dur"].to_numpy(np.float64), "oz": (zs == "O").astype(np.float64),
                "dz": (zs == "D").astype(np.float64)}
        for k in metrics:
            fk, ak = ("xgf", "xga") if k == "xg" else (f"{k[0]}f", f"{k[0]}a")
            cols[fk] = st[f"{side}_{k}"].to_numpy(np.float64)
            cols[ak] = st[f"{o}_{k}"].to_numpy(np.float64)
            if adj:
                cols[fk + "_adj"] = st[f"{side}_{k}_adj"].to_numpy(np.float64)
                cols[ak + "_adj"] = st[f"{o}_{k}_adj"].to_numpy(np.float64)
        num = [c for c in cols if c not in ("game_id", "team", "opp", "role")]
        for c in (_io.SLOTS_H if side == "h" else _io.SLOTS_A):
            p = st[c].to_numpy(float)
            m = np.isfinite(p) & keep
            if not m.any():
                continue
            d = pd.DataFrame({k: cols[k][m] for k in [*by, *num] if k in cols})
            d["player"] = p[m]
            parts.append(d.groupby(keys, sort=False)[num].sum())
        del cols
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts).groupby(level=list(range(len(keys)))).sum()
    del parts
    return out


PG_COLS = ["player", "game_id", "team", "toi", "toi5", "toipp", "toipk", "g", "a1", "a2", "g5", "a1_5", "a2_5", "gpp", "a1pp",
           "a2pp", "ixg", "ixg5", "icf5", "iff", "hits", "blocks", "pen_taken", "pen_drawn", "fo_won", "fo_lost", "cf5", "ca5",
           "xgf5", "xga5", "gf5_on", "ga5_on"]


def player_games(season: int, st: pd.DataFrame | None = None, ev: pd.DataFrame | None = None,
                 sh: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per player-game (skaters): time on ice by strength (seconds), goals and assists (all, 5v5, PP),
    individual xG / attempts, hits, blocks, minor penalties taken / drawn, faceoffs won / lost and on-ice 5v5 goals
    for. The unit table for rates, the box prior and stabilisation."""
    from oddsmarkets.nhl.models import xg as xgm
    season = _io.sid(season)
    st = for_season(season) if st is None else st
    ev = _io.events(season) if ev is None else ev
    sh = xgm.shot_table(season) if sh is None else sh
    if st is None or not len(st):
        return pd.DataFrame(columns=PG_COLS)
    ps = player_sums(st, ("game_id", "team", "role"), metrics=("cf", "gf", "xg"), adj=False).reset_index()
    role = ps["role"].to_numpy(object)
    ps["toi5"] = ps["dur"] * (role == "5v5")
    ps["toipp"] = ps["dur"] * (role == "pp")
    ps["toipk"] = ps["dur"] * (role == "pk")
    r5 = role == "5v5"
    for c_out, c_in in (("cf5", "cf"), ("ca5", "ca"), ("xgf5", "xgf"), ("xga5", "xga"), ("gf5_on", "gf"), ("ga5_on", "ga")):
        ps[c_out] = ps[c_in].to_numpy(float) * r5
    base = ps.groupby(["player", "game_id"]).agg(toi=("dur", "sum"), toi5=("toi5", "sum"), toipp=("toipp", "sum"),
                                                  toipk=("toipk", "sum"), cf5=("cf5", "sum"), ca5=("ca5", "sum"),
                                                  xgf5=("xgf5", "sum"), xga5=("xga5", "sum"), gf5_on=("gf5_on", "sum"),
                                                  ga5_on=("ga5_on", "sum"))
    tm = ps.sort_values("dur").drop_duplicates(["player", "game_id"], keep="last").set_index(["player", "game_id"])["team"]
    base["team"] = tm.reindex(base.index).to_numpy()
    del ps
    e = ev[(ev["shootout"] == 0)]
    ih = e["is_home"].to_numpy(float)
    skf = np.where(ih == 1, e["sk_h"], e["sk_a"]).astype(float)
    ska = np.where(ih == 1, e["sk_a"], e["sk_h"]).astype(float)
    both = (e["g_h"].to_numpy(float) == 1) & (e["g_a"].to_numpy(float) == 1)
    five = both & (skf == 5) & (ska == 5)
    pp = both & (skf > ska)
    goal = (e["type"] == "goal").to_numpy()
    cols: dict = {}
    count = _Counter(e, cols)
    count("g", "shooter", goal)
    count("a1", "assist1", goal)
    count("a2", "assist2", goal)
    count("g5", "shooter", goal & five)
    count("a1_5", "assist1", goal & five)
    count("a2_5", "assist2", goal & five)
    count("gpp", "shooter", goal & pp)
    count("a1pp", "assist1", goal & pp)
    count("a2pp", "assist2", goal & pp)
    count("icf5", "shooter", e["type"].isin(_io.ATTEMPTS).to_numpy() & five)
    count("iff", "shooter", e["type"].isin(_io.UNBLOCKED).to_numpy())
    count("hits", "hitter", (e["type"] == "hit").to_numpy())
    count("blocks", "blocker", (e["type"] == "blocked-shot").to_numpy())
    minor = (e["type"] == "penalty").to_numpy() & ~(e["pen_min"].to_numpy(float) >= 4)
    count("pen_taken", "pen_by", minor)
    count("pen_drawn", "pen_drawn", minor)
    fo = (e["type"] == "faceoff").to_numpy()
    count("fo_won", "winner", fo)
    count("fo_lost", "loser", fo)
    if len(sh):
        s5 = (sh["sk_for"].to_numpy(float) == 5) & (sh["sk_against"].to_numpy(float) == 5) & (sh["empty_net"].to_numpy(float) == 0)
        x = sh["xg"].to_numpy(float)
        p = pd.to_numeric(sh["shooter"], errors="coerce").to_numpy(float)
        ok = np.isfinite(p) & np.isfinite(x)
        d = pd.DataFrame({"player": p[ok], "game_id": sh["game_id"].to_numpy()[ok], "x": x[ok], "x5": (x * s5)[ok]})
        g = d.groupby(["player", "game_id"])
        cols["ixg"] = g["x"].sum()
        cols["ixg5"] = g["x5"].sum()
    out = base.join(pd.DataFrame(cols), how="left")
    for c in PG_COLS:
        if c not in out and c not in ("player", "game_id"):
            out[c] = 0.0
    out = out.reset_index()
    num = [c for c in PG_COLS if c not in ("player", "game_id", "team")]
    out[num] = out[num].fillna(0.0).astype("float32")
    return out[PG_COLS]


class _Counter:
    """count(name, who, mask): per player-game counts of events where `who` is the player (no closures)."""

    def __init__(self, e: pd.DataFrame, cols: dict):
        self.e, self.cols = e, cols

    def __call__(self, name: str, who: str, mask: np.ndarray) -> None:
        p = self.e[who].to_numpy(float)
        m = mask & np.isfinite(p)
        d = pd.DataFrame({"player": p[m], "game_id": self.e["game_id"].to_numpy()[m], "v": np.ones(int(m.sum()))})
        self.cols[name] = d.groupby(["player", "game_id"])["v"].sum()


def player_games_cached(season: int, use_cache: bool = True) -> pd.DataFrame:
    from oddsmarkets.nhl.models import xg as xgm
    season = _io.sid(season)
    f = xgm.current_fit() or {}
    key = _io.file_key(_io.events_path(season), _io.stints_path(season), _io.store_path(season), VERSION, "pg-1",
                       f.get("key"), f.get("platt"))
    return _io.cached_frame("player_games", str(season), key, lambda: player_games(season), use_cache)
