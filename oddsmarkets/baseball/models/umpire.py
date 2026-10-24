"""
Umpires: accuracy, consistency, zone size, per-game scorecards and (2026) ABS challenges.

Built on the called-strike model in `framing.py` (one fit per season).

Per umpire (home plate):
* accuracy = share of called pitches called correctly against the rulebook zone (|plate_x| <= 0.83 ft,
  sz_bot - 0.12 <= plate_z <= sz_top + 0.12: the plate half-width plus a ball radius);
* expected accuracy = mean over his pitches of the probability that the league model *without his
  effect* makes the correct call (p if in the zone, 1 - p if not), so it reflects how hard his pitches
  were; accuracy above expected = accuracy - expected accuracy;
* consistency = share of his calls that agree with his own model (league surface + his effect,
  strike when p > 0.5);
* zone size: called strikes minus expected strikes (league model without him) per 100 called
  pitches, and his random effect (log-odds).

Scorecards (per game): every missed call against the rulebook zone, with its run cost for the
batting team. A call's value is RV(after a ball) - RV(after a strike): count run values from
`re24.count_values` for non-terminal counts, the base-out state for terminal ones (ball four forces
runners; strike three adds an out, and with two outs ends the inning: RE(o, b) is lost). A missed
strike costs the batting team that amount; a missed ball gives it to them. Favour = runs gained by
the home team's batters minus runs gained by the away team's batters from missed calls.

ABS challenges (2026): from the pitch table's challenge columns when present, otherwise the store's
GAME.abs summaries: challenges and overturn rate per team, per challenger (batter, catcher or
pitcher) and per umpire, the run value of each overturned call (the same call values), and best and
worst challengers (value gained per challenge).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _c, framing

MODEL_VERSION = "ump-1"
MIN_CALLED = 500


def _walk(b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    b = np.asarray(b, int)
    new = np.where((b & 1) == 0, b | 1, np.where((b & 2) == 0, b | 3, 7))
    runs = ((b & 7) == 7).astype(float)
    return new, runs


def call_values(d: pd.DataFrame, re: np.ndarray, counts: dict) -> np.ndarray:
    """RV(after ball) - RV(after strike) per called pitch, for the batting team (runs)."""
    rv = counts.get("rv") or {}
    o = d["outs_when_up"].astype(int).clip(0, 2).to_numpy()
    b = np.zeros(len(d), int)
    for bit, c in ((1, "on_1b"), (2, "on_2b"), (4, "on_3b")):
        b |= d[c].notna().to_numpy() * bit
    balls = d["balls"].astype(int).clip(0, 3).to_numpy(); strikes = d["strikes"].astype(int).clip(0, 2).to_numpy()
    cur = np.array([rv.get(f"{x}-{y}", np.nan) for x, y in zip(balls, strikes)], float)
    nb = np.array([rv.get(f"{x + 1}-{y}", np.nan) if x < 3 else np.nan for x, y in zip(balls, strikes)], float)
    ns = np.array([rv.get(f"{x}-{y + 1}", np.nan) if y < 2 else np.nan for x, y in zip(balls, strikes)], float)
    re_now = re[o, b]
    wb, wr = _walk(b)
    after_walk = re[o, wb] + wr - re_now
    after_k = np.where(o + 1 >= 3, -re_now, re[np.minimum(o + 1, 2), b] - re_now)
    # the count run values are relative to a PA's start; differences between counts are what matter
    v_ball = np.where(balls == 3, after_walk, nb - cur)
    v_strike = np.where(strikes == 2, after_k, ns - cur)
    out = v_ball - v_strike
    return np.where(np.isfinite(out), out, 0.125)


def season_tables(d: pd.DataFrame, model: dict, re: np.ndarray, counts: dict) -> dict:
    d = d.copy()
    d["p_full"] = framing.predict(model, d)
    d["p_lg"] = framing.predict(model, d, drop=("ump",))
    d["correct"] = (d["y"] == d["in_zone"]).astype(int)
    d["x_correct"] = np.where(d["in_zone"] == 1, d["p_lg"], 1 - d["p_lg"])
    d["agree_own"] = ((d["p_full"] > 0.5).astype(int) == d["y"]).astype(int)
    d["value"] = call_values(d, re, counts)
    wrong = d["correct"] == 0
    # batting-team runs gained from the call relative to the correct call
    d["impact_bat"] = np.where(wrong, np.where(d["y"] == 1, -d["value"], d["value"]), 0.0)
    d["home_bat"] = d["inning_topbot"].astype(str).str.lower().str.startswith("b")
    g = d[d["ump"].notna()].groupby("ump")
    u = pd.DataFrame({"called": g.size(), "games": g["game_pk"].nunique(), "accuracy": g["correct"].mean(),
                      "x_accuracy": g["x_correct"].mean(), "consistency": g["agree_own"].mean(),
                      "strikes_above_x": g.apply(lambda x: (x["y"] - x["p_lg"]).sum(), include_groups=False),
                      "missed": g["correct"].apply(lambda s: int((s == 0).sum())),
                      "missed_runs": g["impact_bat"].apply(lambda s: float(np.abs(s).sum()))})
    u["acc_above_x"] = u["accuracy"] - u["x_accuracy"]
    u["zone_per100"] = 100 * u["strikes_above_x"] / u["called"]
    u["missed_per_game"] = u["missed"] / u["games"]
    u["runs_per_game"] = u["missed_runs"] / u["games"]
    u["effect"] = u.index.map(model["effects"]["ump"]).astype(float)
    u = u.reset_index().rename(columns={"ump": "pid"}).sort_values("acc_above_x", ascending=False)
    # scorecards
    gg = d.groupby("game_pk")
    sc = pd.DataFrame({"date": gg["game_date"].first(), "home": gg["home_team"].first(), "away": gg["away_team"].first(),
                       "ump": gg["ump"].first(), "called": gg.size(), "missed": gg["correct"].apply(lambda s: int((s == 0).sum())),
                       "accuracy": gg["correct"].mean(), "x_accuracy": gg["x_correct"].mean(),
                       "home_gain": gg.apply(lambda x: x.loc[x["home_bat"], "impact_bat"].sum(), include_groups=False),
                       "away_gain": gg.apply(lambda x: x.loc[~x["home_bat"], "impact_bat"].sum(), include_groups=False),
                       "total_impact": gg["impact_bat"].apply(lambda s: float(np.abs(s).sum()))})
    sc["home_favour"] = sc["home_gain"] - sc["away_gain"]
    sc["favoured"] = np.where(sc["home_favour"] > 0.005, sc["home"], np.where(sc["home_favour"] < -0.005, sc["away"], ""))
    worst = d[wrong].assign(a=lambda x: x["impact_bat"].abs()).sort_values("a", ascending=False).drop_duplicates("game_pk")
    worst = worst.set_index("game_pk")
    for c in ("inning", "balls", "strikes", "plate_x", "plate_z", "y", "impact_bat"):
        sc[f"worst_{c}"] = worst[c].reindex(sc.index)
    return {"umpires": u, "scorecards": sc.reset_index(), "called": d}


def missed_calls(d: pd.DataFrame, game_pk: int) -> pd.DataFrame:
    """The missed calls of one game (for a game page's scorecard)."""
    x = d[(d["game_pk"] == game_pk) & (d["correct"] == 0)]
    return x[["at_bat_number", "pitch_number", "inning", "inning_topbot", "balls", "strikes", "outs_when_up", "plate_x",
              "plate_z", "sz_bot_", "sz_top_", "y", "p_lg", "impact_bat", "batter", "pitcher", "catcher"]]


# ============================================================================ ABS (2026)

CHALLENGE_COL_HINTS = ("challenge", "abs_")


def abs_pitch_columns(pitches: pd.DataFrame) -> list[str]:
    return [c for c in pitches.columns if any(h in c.lower() for h in CHALLENGE_COL_HINTS)]


DES_RE = r"^(?P<who>.*?) challenged \((?P<kind>[^)]*)\), call on the field was (?P<res>\w+)"


def abs_from_des(pitches: pd.DataFrame, store: dict | None, re: np.ndarray, counts: dict) -> dict:
    """ABS challenges from Savant's play text (2026): '<name> challenged (pitch result), call on the field was
    overturned|confirmed: ...'. The text sits on the PA's last pitch, so these are the challenges of
    PA-ending calls (strike three / ball four); manager replay reviews of other plays are counted
    separately. The challenger is matched by name to the batter, catcher (fielder_2) or pitcher."""
    if "des" not in pitches:
        return {"ok": False, "reason": "no des column"}
    d = pitches["des"].astype(object).fillna("").astype(str)
    m = d.str.contains(" challenged (", regex=False)
    if not m.any():
        return {"ok": False, "reason": "no challenges in des"}
    x = pitches[m].copy()
    ex = d[m].str.extract(DES_RE)
    x["who"], x["kind"], x["res"] = ex["who"].str.strip(), ex["kind"], ex["res"].str.lower()
    x["overturned"] = (x["res"] == "overturned").astype(int)
    replay = x[x["kind"] != "pitch result"]
    a = x[x["kind"] == "pitch result"].copy()
    players = (store or {}).get("players") or {}
    def nm(pid):
        try:
            return _c_name(players.get(str(int(pid)), {}).get("name"))
        except (TypeError, ValueError):
            return None
    who = a["who"].map(_c_name)
    # the play text after the colon starts with the batter's name; Savant's player_name ("Last, First") is the
    # pitcher in a pitcher-keyed search; the catcher is the remaining challenger
    rest = d[m][a.index].str.split(": ", n=1).str[1].fillna("").map(_c_name)
    pn = a["player_name"].astype(str).map(lambda s: " ".join(reversed([t.strip() for t in s.split(",", 1)])) if "," in s else s)         if "player_name" in a else pd.Series(None, index=a.index)
    pn = pn.map(_c_name)
    roles = [resolve_challenger(w, b, pt, c, r, nm, pnm)
             for w, b, c, pt, r, pnm in zip(who, a["batter"], a.get("fielder_2", pd.Series(np.nan, index=a.index)), a["pitcher"],
                                            rest, pn)]
    a["role"] = [r[0] for r in roles]
    a["challenger"] = [r[1] for r in roles]
    a["y"] = a["description"].astype(str).eq("called_strike").astype(int)        # the call after review
    v = call_values(a.assign(on_1b=a.get("on_1b"), on_2b=a.get("on_2b"), on_3b=a.get("on_3b")), re, counts)
    a["value"] = np.where(a["overturned"] == 1, v, 0.0)       # runs gained by the challenging side
    top = a["inning_topbot"].astype(str).str.lower().str.startswith("t")
    bat_team = np.where(top, a["away_team"], a["home_team"]); fld_team = np.where(top, a["home_team"], a["away_team"])
    a["team"] = np.where(a["role"] == "batter", bat_team, fld_team)
    out = {"ok": True, "source": "des", "scope": "PA-ending calls", "n": int(len(a)), "games": int(a["game_pk"].nunique()),
           "overturn_rate": float(a["overturned"].mean()) if len(a) else None,
           "value_per_challenge": float(a["value"].mean()) if len(a) else None,
           "value_per_overturn": float(a.loc[a["overturned"] == 1, "value"].mean()) if a["overturned"].any() else None}
    out["by_role"] = {r: {"n": int(len(g)), "overturn_rate": float(g["overturned"].mean()), "runs": float(g["value"].sum())}
                      for r, g in a.groupby("role")}
    tm = a.groupby("team").agg(n=("overturned", "size"), won=("overturned", "sum"), runs=("value", "sum"))
    tm["rate"] = tm["won"] / tm["n"]
    out["teams"] = _c.frame_rows(tm.reset_index().sort_values("runs", ascending=False))
    ch = a[a["challenger"].notna()].groupby(["challenger", "role"]).agg(
        n=("overturned", "size"), won=("overturned", "sum"), runs=("value", "sum")).reset_index()
    ch["rate"] = ch["won"] / ch["n"]
    ch["runs_per"] = ch["runs"] / ch["n"]
    ch = ch.sort_values(["runs", "rate"], ascending=False)
    out["challengers"] = _c.frame_rows(ch)
    out["best"] = _c.frame_rows(ch[ch["n"] >= 3].head(10))
    out["worst"] = _c.frame_rows(ch[ch["n"] >= 3].sort_values(["rate", "n"], ascending=[True, False]).head(10))
    if "ump" in a or "game_pk" in a:
        gm = {int(k): (g or {}).get("umpire_hp") for k, g in ((store or {}).get("games") or {}).items()}
        a["ump"] = a["game_pk"].astype(np.int64).map(gm)
        um = a[a["ump"].notna()].groupby("ump").agg(n=("overturned", "size"), overturned=("overturned", "sum"))
        um["rate"] = um["overturned"] / um["n"]
        out["umpires"] = _c.frame_rows(um.reset_index().sort_values("overturned", ascending=False))
    out["replay"] = {"n": int(len(replay)), "overturn_rate": float(replay["overturned"].mean()) if len(replay) else None,
                     "by_kind": replay.groupby("kind")["overturned"].agg(["size", "mean"]).reset_index().values.tolist()}
    return out


def _pid(x) -> str | None:
    try:
        return None if x is None or pd.isna(x) else str(int(x))
    except (TypeError, ValueError):
        return None


def resolve_challenger(who: str | None, batter, pitcher, catcher, rest: str | None, name_of, pitcher_name: str | None = None
                       ) -> tuple[str, str | None]:
    """(role, player id) of the person named in an ABS challenge's play text. `who` and `rest` (the play text after the
    colon, which starts with the batter's name) are already folded by `_c_name`; `name_of(pid)` gives a folded name.
    The batter is matched by name or by the play text, the pitcher by name (or Savant's player_name), the catcher by
    name, and an unmatched name falls to the catcher (fielder_2): batters and pitchers are named in the row, the catcher
    is the one who is not."""
    b, pt, c = _pid(batter), _pid(pitcher), _pid(catcher)
    if not who:
        return ("unknown", None)
    if b and (who == name_of(b) or (rest or "").startswith(who)):
        return ("batter", b)
    if pt and (who == name_of(pt) or (pitcher_name and who == pitcher_name)):
        return ("pitcher", pt)
    if c:
        return ("catcher", c)
    return ("unknown", None)


def _c_name(s) -> str | None:
    if not s or not isinstance(s, str):
        return None
    import unicodedata
    t = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in t if not unicodedata.combining(ch)).lower().replace(".", "").replace(" jr", "").strip()


def abs_analytics(pitches: pd.DataFrame, store: dict | None, re: np.ndarray, counts: dict) -> dict:
    """ABS challenge tables: Savant's play text (des) first, then pitch-level challenge columns, then the
    store's GAME.abs summaries."""
    r = abs_from_des(pitches, store, re, counts)
    if r.get("ok"):
        return r
    out: dict[str, Any] = {"ok": False}
    cols = abs_pitch_columns(pitches)
    desc = pitches["description"].astype(str) if "description" in pitches else pd.Series("", index=pitches.index)
    flag = pd.Series(False, index=pitches.index)
    over = pd.Series(np.nan, index=pitches.index)
    who = pd.Series(None, index=pitches.index, dtype=object)
    for c in cols:
        s = pitches[c]
        lc = c.lower()
        if "overturn" in lc or "success" in lc or "result" in lc:
            v = s.astype(str).str.lower()
            over = over.where(s.isna(), v.isin(["1", "true", "overturned", "yes", "success", "1.0"]).astype(float))
            flag |= s.notna()
        elif "by" in lc or "challenger" in lc or "role" in lc or "player" in lc:
            who = who.where(s.isna(), s.astype(str))
            flag |= s.notna()
        elif s.dtype == bool or set(pd.unique(s.dropna().astype(str).str.lower())) <= {"0", "1", "true", "false", "0.0", "1.0"}:
            flag |= s.astype(str).str.lower().isin(["1", "true", "1.0"])
        else:
            flag |= s.notna() & (s.astype(str).str.strip() != "")
    flag |= desc.str.contains("challenge", case=False, na=False)
    if flag.any():
        x = pitches[flag].copy()
        if over.isna().all():
            over = desc.str.contains("overturn", case=False, na=False).astype(float)
        x["overturned"] = over[flag].fillna(0).astype(int)
        x["challenger"] = who[flag]
        x["ump"] = x["umpire"] if "umpire" in x else None
        if all(c in x for c in ("balls", "strikes", "outs_when_up")):
            d = x.assign(y=x["description"].astype(str).str.contains("strike").astype(int))
            v = call_values(d, re, counts)
            x["value"] = v
        out = {"ok": True, "source": "pitches", "n": int(len(x)), "overturn_rate": float(x["overturned"].mean()),
               "columns": cols}
        x["bat_team"] = np.where(x["inning_topbot"].astype(str).str.lower().str.startswith("t"), x["away_team"], x["home_team"])
        tm = x.groupby("bat_team")["overturned"].agg(["size", "mean"]).reset_index()
        out["by_batting_team"] = _c.frame_rows(tm)
        if x["challenger"].notna().any():
            ch = x.groupby("challenger").agg(n=("overturned", "size"), won=("overturned", "sum"),
                                             value=("value", lambda s: float(np.nansum(s.to_numpy()))) if "value" in x else ("overturned", "size"))
            ch["rate"] = ch["won"] / ch["n"]
            out["challengers"] = _c.frame_rows(ch.reset_index().sort_values("rate", ascending=False))
        if "value" in x:
            out["mean_value_overturned"] = float(np.nanmean(x.loc[x["overturned"] == 1, "value"])) if (x["overturned"] == 1).any() else None
        return out
    # store summaries
    rows = []
    for gpk, g in ((store or {}).get("games") or {}).items():
        a = (g or {}).get("abs")
        if not isinstance(a, dict):
            continue
        for side in ("home", "away"):
            s = a.get(side) or {}
            if not isinstance(s, dict):
                continue
            used = _num(s, ("used", "challenges", "attempts", "total"))
            won = _num(s, ("overturned", "successful", "won", "success"))
            rows.append({"gpk": gpk, "team": g.get(side), "side": side, "used": used, "won": won})
    if rows:
        t = pd.DataFrame(rows)
        tt = t.groupby("team")[["used", "won"]].sum()
        tt["rate"] = tt["won"] / tt["used"].replace(0, np.nan)
        out = {"ok": True, "source": "store", "games": int(t["gpk"].nunique()), "used": float(t["used"].sum()),
               "won": float(t["won"].sum()), "overturn_rate": float(t["won"].sum() / max(t["used"].sum(), 1)),
               "teams": _c.frame_rows(tt.reset_index().sort_values("rate", ascending=False))}
    else:
        out = {"ok": False, "reason": "no ABS challenge data in pitches or store"}
    return out


def _num(s: dict, keys: tuple[str, ...]) -> float:
    for k, v in s.items():
        if any(x in str(k).lower() for x in keys):
            try:
                return float(v if not isinstance(v, (list, tuple)) else len(v))
            except (TypeError, ValueError):
                continue
    return 0.0


# ============================================================================ season driver

def season_result(level: str, season: int, pitches: pd.DataFrame | None = None, store: dict | None = None,
                  fr: dict | None = None) -> dict | None:
    from oddsmarkets.baseball.models import re24
    own = pitches is None
    if own:
        cols = list(dict.fromkeys(framing.COLUMNS + ["game_type"]))
        pitches = _c.load_pitches(level, season, cols)
        if pitches is None or not len(pitches):
            return None
        store = store or _c.load_store(level, season)
    fr = fr or framing.season_fit(level, season, pitches, store)
    rs = re24.statcast_season(level, season, pitches=pitches, with_wpa=False)
    re, counts = rs["re"]["re"], rs["counts"]
    t = season_tables(fr["called"], fr["model"], re, counts)
    if int(season) >= 2026:
        allp = pitches
        if own:
            extra = [c for c in _c.parquet_columns(_c.pitch_path(level, season)) if any(h in c.lower() for h in CHALLENGE_COL_HINTS)] + ["des"]
            if extra:
                allp = _c.load_pitches(level, season, list(dict.fromkeys(framing.COLUMNS + extra)))
        t["abs"] = abs_analytics(allp, store, re, counts)
    else:
        t["abs"] = {"ok": False, "reason": "ABS challenges from 2026"}
    t["framing"] = fr
    return t


def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    path = _c.pitch_path(level, season)
    if not path.exists():
        return {"ok": False, "reason": f"no pitch table for {level} {season}"}

    def build():
        r = season_result(level, season)
        if r is None:
            return {"ok": False, "reason": "empty"}
        u = r["umpires"]
        return {"ok": True, "version": MODEL_VERSION, "umpires": _c.frame_rows(u),
                "leaders": _c.frame_rows(u[u["called"] >= MIN_CALLED].head(10)),
                "scorecards": _c.frame_rows(r["scorecards"]), "abs": r["abs"],
                "league": {"accuracy": float(r["called"]["correct"].mean()),
                           "missed_per_game": float((r["called"]["correct"] == 0).sum() / max(r["called"]["game_pk"].nunique(), 1))}}
    return _c.cached("umpire", f"{level}_{season}", _c.file_key(path, MODEL_VERSION), build, use_cache)


def export_fits(level: str = "mlb", season: int | None = None) -> dict:
    """Umpire tables are season outputs; the committed piece is the framing surface (framing.export_fits)."""
    return framing.export_fits(level, season)
