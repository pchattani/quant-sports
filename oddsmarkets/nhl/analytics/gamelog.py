"""
Per player-game logs for the valuation, trade-rating and fantasy layers (valuation.py, moves.py, fantasy.py).

One compact table per season, cached under <cache>/analytics/gamelog/ on its inputs' signatures:

  sk  skater-games: season, game_id, date, gt ("R" regular season / "P" playoffs), team, opp, home, pid, pos (C/L/R/D),
      the boxscore's official counts (g, a, pm, pim, hits, blk, sog, ppg; toi in minutes) joined to the player-game
      table of the models (models/_stints.player_games: toi5 / toipp / toipk minutes, power-play points ppp = PP goals +
      PP assists, a5 / g5 at 5v5, ixg, on-ice 5v5 xgf5 / xga5 / gf5 / ga5) and the shot table (models/xg.shot_table:
      ixg_pp on the power play, ixg_es at even strength, both goalies in).
  gk  goalie-games: season, game_id, date, gt, team, opp, home, pid, toi, sa, sv, ga, dec (W / L / O), start, xga (xG of
      the unblocked shots he faced, empty net out) and ga_x (goals on those shots).
  tg  team-games: season, game_id, date, gt, team, opp, home, gf, ga (final score, the shootout winner's goal
      included), win, ot, xgf, xga (unblocked shots, all situations), sf, sa (shots on goal), p_win (the game model's
      pre-game probability in the season's schedule.json: walk-forward, frozen or live; None when absent).

Boxscores (data/nhl/box/<S>/<game>.json.gz) are parsed once each: their per-game rows are kept with the file's size and
mtime and only new or changed files are read again, so the current season's log costs a second or two an hour.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nhl import analytics as an

logger = logging.getLogger(__name__)

VERSION = 1
SK_INT = ["g", "a", "pm", "pim", "hits", "blk", "sog", "ppg"]


def box_dir(season: int) -> Path:
    return an.raw_root() / "box" / str(int(season))


def _cache_dir() -> Path:
    return an.an_cache() / "gamelog"


def _mins(s: Any) -> float:
    try:
        m, sec = str(s).split(":")
        return int(m) + int(sec) / 60.0
    except (ValueError, AttributeError):
        return 0.0


def _gtype(gid: Any) -> str:
    s = str(gid)
    return "P" if s[4:6] == "03" else "R" if s[4:6] == "02" else "X"


def parse_box(d: dict) -> tuple[list[list], list[list]]:
    """(skater rows [game_id, team, opp, home, pid, pos, toi, g, a, pm, pim, hits, blk, sog, ppg],
    goalie rows [game_id, team, opp, home, pid, toi, sa, sv, ga, dec, start])."""
    gid = int(d.get("id") or 0)
    home_t = ((d.get("homeTeam") or {}).get("abbrev"))
    away_t = ((d.get("awayTeam") or {}).get("abbrev"))
    sk: list[list] = []
    gk: list[list] = []
    pbs = d.get("playerByGameStats") or {}
    for side, team, opp, home in (("homeTeam", home_t, away_t, 1), ("awayTeam", away_t, home_t, 0)):
        node = pbs.get(side) or {}
        for grp in ("forwards", "defense"):
            for p in node.get(grp) or []:
                pid = p.get("playerId")
                if not pid:
                    continue
                pos = str(p.get("position") or ("D" if grp == "defense" else "C"))[:1]
                sk.append([gid, team, opp, home, int(pid), pos, _mins(p.get("toi")), int(p.get("goals") or 0), int(p.get("assists") or 0),
                           int(p.get("plusMinus") or 0), int(p.get("pim") or 0), int(p.get("hits") or 0), int(p.get("blockedShots") or 0),
                           int(p.get("sog") or 0), int(p.get("powerPlayGoals") or 0)])
        for p in node.get("goalies") or []:
            pid = p.get("playerId")
            toi = _mins(p.get("toi"))
            if not pid or toi <= 0:
                continue
            sa = int(p.get("shotsAgainst") or 0)
            sv = int(p.get("saves") or 0)
            ga = int(p.get("goalsAgainst") or 0)
            dec = str(p.get("decision") or "")[:1]
            gk.append([gid, team, opp, home, int(pid), toi, sa, sv, ga, dec, 1 if p.get("starter") else 0])
    return sk, gk


def _file_sig(p: Path) -> str:
    st = p.stat()
    return f"{st.st_size}-{st.st_mtime_ns}"


def box_rows(season: int) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """All boxscores of a season as (skater rows, goalie rows, signature), re-reading only new or changed files."""
    season = int(season)
    d = box_dir(season)
    files = sorted(d.glob("*.json.gz")) + sorted(d.glob("*.json")) if d.exists() else []
    sigs = {}
    for f in files:
        gid = f.name.split(".")[0]
        if gid.isdigit() and _gtype(gid) in ("R", "P"):
            try:
                sigs[gid] = _file_sig(f)
            except OSError:
                continue
    cdir = _cache_dir()
    meta_p, sk_p, gk_p = cdir / f"box_{season}.json", cdir / f"box_{season}_sk.parquet", cdir / f"box_{season}_gk.parquet"
    meta = an.read_json(meta_p) or {}
    old_sigs = meta.get("sigs") or {}
    sk_old = gk_old = None
    if meta.get("version") == VERSION and sk_p.exists() and gk_p.exists():
        try:
            sk_old, gk_old = pd.read_parquet(sk_p), pd.read_parquet(gk_p)
        except Exception:                                        # noqa: BLE001
            sk_old = gk_old = None
    if sk_old is None:
        old_sigs = {}
    todo = [g for g, s in sigs.items() if old_sigs.get(g) != s]
    keep = {int(g) for g, s in sigs.items() if old_sigs.get(g) == s}
    sk_new: list[list] = []
    gk_new: list[list] = []
    for gid in todo:
        p = d / f"{gid}.json.gz"
        if not p.exists():
            p = d / f"{gid}.json"
        try:
            if p.name.endswith(".gz"):
                with gzip.open(p, "rb") as fh:
                    doc = json.loads(fh.read())
            else:
                doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError, EOFError):
            continue
        st = str(doc.get("gameState") or "").upper()
        if st not in ("OFF", "FINAL"):
            sigs.pop(gid, None)                                   # not final: read again next time
            continue
        a, b = parse_box(doc)
        sk_new += a
        gk_new += b
    skc = ["game_id", "team", "opp", "home", "pid", "pos", "toi"] + SK_INT
    gkc = ["game_id", "team", "opp", "home", "pid", "toi", "sa", "sv", "ga", "dec", "start"]
    parts_s = [pd.DataFrame(sk_new, columns=skc)] if sk_new else []
    parts_g = [pd.DataFrame(gk_new, columns=gkc)] if gk_new else []
    if sk_old is not None and keep:
        parts_s.insert(0, sk_old[sk_old["game_id"].isin(keep)])
        parts_g.insert(0, gk_old[gk_old["game_id"].isin(keep)])
    sk = pd.concat(parts_s, ignore_index=True) if parts_s else pd.DataFrame(columns=skc)
    gk = pd.concat(parts_g, ignore_index=True) if parts_g else pd.DataFrame(columns=gkc)
    if todo or not meta_p.exists():
        cdir.mkdir(parents=True, exist_ok=True)
        sk.to_parquet(sk_p, index=False)
        gk.to_parquet(gk_p, index=False)
        an.write_json(meta_p, {"version": VERSION, "sigs": sigs})
    sig = hashlib.sha1(json.dumps(sorted(sigs.items())).encode()).hexdigest()[:16]
    return sk, gk, sig


def _key_text(kind: str, season: int) -> str:
    p = an.cache_root() / kind / f"{season}.key"
    try:
        return p.read_text(encoding="utf-8").strip()[:40]
    except OSError:
        return ""


def _player_games(season: int, current: bool) -> pd.DataFrame | None:
    """The models' player-game table: read from its cache for a past season, refreshed through the model for the
    current one (a cache hit after the catalogues' build)."""
    p = an.cache_root() / "player_games" / f"{season}.parquet"
    try:
        if p.exists() and not current:
            return pd.read_parquet(p)
        from oddsmarkets.nhl.models import _stints
        return _stints.player_games_cached(season)
    except Exception as exc:                                     # noqa: BLE001
        logger.warning("player_games %s unavailable: %s", season, exc)
        return pd.read_parquet(p) if p.exists() else None


def _shot_table(season: int, current: bool) -> pd.DataFrame | None:
    p = an.cache_root() / "xg_shots" / f"{season}.parquet"
    cols = ["game_id", "team", "shooter", "goalie", "sk_for", "sk_against", "empty_net", "goal", "xg", "type"]
    try:
        if p.exists() and not current:
            return pd.read_parquet(p, columns=cols)
        from oddsmarkets.nhl.models import xg as xgm
        t = xgm.shot_table(season)
        return t[[c for c in cols if c in t.columns]]
    except Exception as exc:                                     # noqa: BLE001
        logger.warning("shot table %s unavailable: %s", season, exc)
        try:
            return pd.read_parquet(p, columns=cols) if p.exists() else None
        except Exception:                                        # noqa: BLE001
            return None


def _store_games(season: int) -> dict[int, dict]:
    st = an.load_store(season) or {}
    gs = st.get("games") or {}
    out = {}
    for k, g in (gs.items() if isinstance(gs, dict) else ((x.get("game_id"), x) for x in gs)):
        try:
            out[int(k)] = g
        except (TypeError, ValueError):
            continue
    return out


def _pwin(season: int) -> dict[int, float]:
    """{game_id: the game model's pre-game P(home wins)} from the season's schedule.json."""
    sch = an.read_json(an.data_root() / str(season) / "schedule.json") or {}
    out = {}
    for c in sch.get("games") or []:
        p = (c.get("model") or {}).get("p_home")
        if p is not None:
            try:
                out[int(c["game_id"])] = float(p)
            except (TypeError, ValueError, KeyError):
                continue
    return out


def season_log(season: int, current: bool = False, use_cache: bool = True) -> dict:
    """{"sk", "gk", "tg"} DataFrames for one season (empty frames without boxscores)."""
    season = int(season)
    t0 = time.perf_counter()
    sk_b, gk_b, bsig = box_rows(season)
    pw = _pwin(season)                 # content, not mtime: the build rewrites schedule.json of the page seasons hourly
    psig = hashlib.sha1(json.dumps(sorted(pw.items())).encode()).hexdigest()[:16]
    games = _store_games(season)
    gsig = hashlib.sha1(json.dumps(sorted((k, str(v.get("status")), v.get("hs"), v.get("as"), str(v.get("date"))) for k, v in games.items()),
                                   default=str).encode()).hexdigest()[:16]
    key = hashlib.sha1(json.dumps([VERSION, bsig, _key_text("player_games", season), _key_text("xg_shots", season), psig, gsig]).encode()).hexdigest()[:20]
    cdir = _cache_dir()
    paths = {k: cdir / f"log_{season}_{k}.parquet" for k in ("sk", "gk", "tg")}
    kp = cdir / f"log_{season}.key"
    if use_cache and kp.exists() and all(p.exists() for p in paths.values()):
        try:
            if kp.read_text(encoding="utf-8").strip() == key:
                return {k: pd.read_parquet(p) for k, p in paths.items()}
        except (OSError, ValueError):
            pass
    dates = {g: str((r or {}).get("date") or "")[:10] for g, r in games.items()}
    sk = sk_b.copy()
    gk = gk_b.copy()
    for df in (sk, gk):
        df["season"] = season
        df["date"] = df["game_id"].map(dates).fillna("")
        df["gt"] = df["game_id"].map(_gtype)
    pg = _player_games(season, current)
    if pg is not None and len(pg) and len(sk):
        pg = pg.copy()
        pg["pid"] = pd.to_numeric(pg["player"], errors="coerce").astype("Int64")
        pg = pg.dropna(subset=["pid"])
        pg["pid"] = pg["pid"].astype("int64")
        add = pd.DataFrame({"game_id": pg["game_id"].astype("int64"), "pid": pg["pid"],
                            "toi5": pg["toi5"] / 60.0, "toipp": pg["toipp"] / 60.0, "toipk": pg["toipk"] / 60.0,
                            "ppp": pg["gpp"] + pg["a1pp"] + pg["a2pp"], "app": pg["a1pp"] + pg["a2pp"], "gpp": pg["gpp"],
                            "g5": pg["g5"], "a5": pg["a1_5"] + pg["a2_5"], "ixg": pg["ixg"], "iff": pg["iff"],
                            "xgf5": pg["xgf5"], "xga5": pg["xga5"], "gf5": pg["gf5_on"], "ga5": pg["ga5_on"]})
        sk = sk.merge(add, on=["game_id", "pid"], how="left")
    shots = _shot_table(season, current)
    if shots is not None and len(shots):
        s = shots
        sf = s["sk_for"].to_numpy(float)
        sa = s["sk_against"].to_numpy(float)
        en = s["empty_net"].to_numpy(float) if "empty_net" in s else np.zeros(len(s))
        x = s["xg"].to_numpy(float)
        shooter = pd.to_numeric(s["shooter"], errors="coerce").to_numpy(float)
        ok = np.isfinite(shooter) & np.isfinite(x)
        d = pd.DataFrame({"game_id": s["game_id"].to_numpy(np.int64)[ok], "pid": shooter[ok].astype(np.int64),
                          "ixg_pp": (x * ((sf > sa) & (en == 0)))[ok], "ixg_es": (x * (sf == sa))[ok]})
        d = d.groupby(["game_id", "pid"], as_index=False).sum()
        if len(sk):
            sk = sk.merge(d, on=["game_id", "pid"], how="left")
        goalie = pd.to_numeric(s["goalie"], errors="coerce").to_numpy(float)
        okg = np.isfinite(goalie) & np.isfinite(x) & (en == 0)
        dg = pd.DataFrame({"game_id": s["game_id"].to_numpy(np.int64)[okg], "pid": goalie[okg].astype(np.int64), "xga": x[okg],
                           "ga_x": s["goal"].to_numpy(float)[okg]})
        dg = dg.groupby(["game_id", "pid"], as_index=False).sum()
        if len(gk):
            gk = gk.merge(dg, on=["game_id", "pid"], how="left")
        team = s["team"].astype(str).to_numpy()
        dt = pd.DataFrame({"game_id": s["game_id"].to_numpy(np.int64), "team": team, "x": x})
        dt = dt[np.isfinite(dt["x"].to_numpy())].groupby(["game_id", "team"], as_index=False)["x"].sum()
    else:
        dt = pd.DataFrame(columns=["game_id", "team", "x"])
    for c in ("toi5", "toipp", "toipk", "ppp", "app", "gpp", "g5", "a5", "ixg", "iff", "xgf5", "xga5", "gf5", "ga5", "ixg_pp", "ixg_es"):
        if c not in sk:
            sk[c] = np.nan
    if "ppp" in sk:
        sk["ppp"] = sk["ppp"].where(sk["ppp"].notna(), sk["ppg"])
    for c in ("xga", "ga_x"):
        if c not in gk:
            gk[c] = np.nan
    # team-games from the store's final games
    tg_rows = []
    for gid, g in games.items():
        if _gtype(gid) not in ("R", "P") or str(g.get("status") or "").lower() not in ("final", "off", "official"):
            continue
        h, a = g.get("home"), g.get("away")
        hs, as_ = g.get("hs"), g.get("as")
        if h is None or a is None or hs is None or as_ is None:
            continue
        ph = pw.get(gid)
        for team, opp, home, gf, ga in ((h, a, 1, hs, as_), (a, h, 0, as_, hs)):
            tg_rows.append([season, gid, dates.get(gid, ""), _gtype(gid), team, opp, home, int(gf), int(ga), int(gf > ga),
                            int(bool(g.get("ot")) or bool(g.get("so"))), None if ph is None else (ph if home else 1 - ph)])
    tg = pd.DataFrame(tg_rows, columns=["season", "game_id", "date", "gt", "team", "opp", "home", "gf", "ga", "win", "ot", "p_win"])
    if len(tg):
        xm = {(int(r.game_id), str(r.team)): float(r.x) for r in dt.itertuples()} if len(dt) else {}
        tg["xgf"] = [xm.get((g, t)) for g, t in zip(tg["game_id"], tg["team"])]
        tg["xga"] = [xm.get((g, o)) for g, o in zip(tg["game_id"], tg["opp"])]
        if len(sk):
            sog = sk.groupby(["game_id", "team"])["sog"].sum()
            tg["sf"] = [sog.get((g, t)) for g, t in zip(tg["game_id"], tg["team"])]
            tg["sa"] = [sog.get((g, o)) for g, o in zip(tg["game_id"], tg["opp"])]
        else:
            tg["sf"] = tg["sa"] = np.nan
    else:
        for c in ("xgf", "xga", "sf", "sa"):
            tg[c] = []
    # compact dtypes
    for c in ("toi", "toi5", "toipp", "toipk", "ixg", "ixg_pp", "ixg_es", "xgf5", "xga5", "iff", "ppp", "app", "gpp", "g5", "a5", "gf5", "ga5"):
        if c in sk:
            sk[c] = pd.to_numeric(sk[c], errors="coerce").astype("float32")
    for c in ("toi", "xga", "ga_x"):
        gk[c] = pd.to_numeric(gk[c], errors="coerce").astype("float32")
    for c in ("xgf", "xga", "sf", "sa", "p_win"):
        tg[c] = pd.to_numeric(tg[c], errors="coerce").astype("float32")
    sk = sk.sort_values(["date", "game_id", "team", "pid"]).reset_index(drop=True)
    gk = gk.sort_values(["date", "game_id", "team", "pid"]).reset_index(drop=True)
    tg = tg.sort_values(["date", "game_id", "team"]).reset_index(drop=True)
    out = {"sk": sk, "gk": gk, "tg": tg}
    try:
        cdir.mkdir(parents=True, exist_ok=True)
        for k, p in paths.items():
            out[k].to_parquet(p, index=False)
        kp.write_text(key, encoding="utf-8")
    except OSError as exc:
        logger.warning("gamelog cache %s not written: %s", season, exc)
    logger.info("gamelog %s: %d skater-games, %d goalie-games, %d team-games (%.1f s)", season, len(sk), len(gk), len(tg),
                time.perf_counter() - t0)
    return out


def logs(seasons: list[int], current: int | None = None) -> dict:
    """The seasons' logs concatenated (seasons without boxscores skipped)."""
    parts: dict[str, list] = {"sk": [], "gk": [], "tg": []}
    for s in sorted(seasons):
        if not box_dir(s).exists():
            continue
        L = season_log(s, current=(current is not None and int(s) == int(current)))
        for k in parts:
            if len(L[k]):
                parts[k].append(L[k])
    return {k: (pd.concat(v, ignore_index=True) if v else pd.DataFrame()) for k, v in parts.items()}
