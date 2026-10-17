"""
The enriched pitch table every builder-B model reads: one season at a time.

`enrich(df)` takes raw Savant columns and adds
* physics (`physics.add_physics`): vaa, haa, ivb, hb, hb_arm, decision-point position, spin efficiency, ...
* outcome flags (`_io.outcomes`), `family`, `fam` (family code), `pt` (pitch-type code), `cnt` (count code
  b*3+s), `platoon` (1 = same hand), `x_away` (plate_x, positive away from the batter), `z_rel` (plate height
  as a share of the batter's zone: 0 = bottom, 1 = top), `in_zone`;
* the pitcher's primary fastball for the season (most-thrown of FF / SI, else FC, else the hardest type) and
  each pitch's differentials to it: `d_velo`, `d_ivb`, `d_hb` (arm side);
* sequence features from the previous pitch of the same plate appearance: `prev_pt`, `prev_same`,
  `d_velo_prev`, `d_ivb_prev`, `d_hb_prev`, `dp_dist` (in, at the decision point), `plate_dist` (in);
* `game_pitch` (the pitcher's pitch count in the game before this pitch), `rv` (delta_run_exp, runs from the
  batting side) and `rv_dn` (the same with in-play luck removed: rv + b (xwOBA - wOBA), b the season's
  slope of delta_run_exp on woba_value over balls in play).

`prepared(level, season)` caches the enriched season as Parquet under cache_root()/prep/, keyed on the raw
file, so the stuff, location, swing and tunneling models share one pass.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _io, physics

PREP_VERSION = "prep-3"

RAW_COLS = ["game_pk", "game_date", "game_type", "at_bat_number", "pitch_number", "pitcher", "batter", "stand",
            "p_throws", "inning", "inning_topbot", "outs_when_up", "balls", "strikes", "on_1b", "on_2b", "on_3b",
            "pitch_type", "release_speed", "effective_speed", "release_spin_rate", "spin_axis", "release_extension",
            "release_pos_x", "release_pos_y", "release_pos_z", "arm_angle", "pfx_x", "pfx_z", "plate_x", "plate_z",
            "sz_top", "sz_bot", "zone", "vx0", "vy0", "vz0", "ax", "ay", "az", "api_break_z_with_gravity",
            "api_break_x_arm", "api_break_x_batter_in", "description", "type", "events", "bb_type", "launch_speed",
            "launch_angle", "estimated_woba_using_speedangle", "woba_value", "woba_denom", "delta_run_exp",
            "bat_speed", "swing_length", "attack_angle", "attack_direction", "swing_path_tilt",
            "intercept_ball_minus_batter_pos_x_inches", "intercept_ball_minus_batter_pos_y_inches",
            "n_thruorder_pitcher", "pitcher_days_since_prev_game", "home_team", "away_team"]

DROP_AFTER = ["description", "events", "bb_type", "api_break_z_with_gravity", "api_break_x_arm", "api_break_x_batter_in", "pfx_x_calc", "pfx_z_calc",
              "brk_z_grav", "brk_x_arm", "brk_x_in", "vx0", "vy0", "vz0", "ax", "ay", "az", "type"]


def _num(df: pd.DataFrame, c: str) -> pd.Series:
    return pd.to_numeric(df[c], errors="coerce") if c in df else pd.Series(np.nan, index=df.index)


def fastball_refs(df: pd.DataFrame) -> pd.DataFrame:
    """Per pitcher: primary fastball type and its mean velo, IVB and arm-side HB."""
    d = df[["pitcher", "pitch_type", "release_speed", "ivb", "hb_arm"]].copy()
    d = d[d["pitch_type"].notna()]
    g = d.groupby(["pitcher", "pitch_type"], observed=True).agg(
        n=("release_speed", "size"), velo=("release_speed", "mean"), ivb=("ivb", "mean"), hb=("hb_arm", "mean"))
    g = g.reset_index()
    g["rank"] = np.select([g["pitch_type"].isin(["FF", "SI"]), g["pitch_type"].eq("FC")], [0, 1], 2)
    g = g.sort_values(["pitcher", "rank", "n", "velo"], ascending=[True, True, False, False])
    # the hardest type when the pitcher throws no FF/SI/FC: rank 2 rows sorted by velo
    hard = g[g["rank"] == 2].sort_values(["pitcher", "velo"], ascending=[True, False])
    best = pd.concat([g[g["rank"] < 2], hard]).drop_duplicates("pitcher", keep="first")
    return best.set_index("pitcher")[["pitch_type", "velo", "ivb", "hb"]].rename(
        columns={"pitch_type": "fb_type", "velo": "fb_velo", "ivb": "fb_ivb", "hb": "fb_hb"})


def enrich(df: pd.DataFrame, inplay_slope: float | None = None) -> pd.DataFrame:
    df = df.copy()
    for c in RAW_COLS:
        if c not in df:
            df[c] = np.nan
    for c in ("game_pk", "at_bat_number", "pitch_number", "pitcher", "batter"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(-1).astype("int64")
    df["game_date"] = df["game_date"].astype(str).str[:10]
    df = _io.sort_pitches(df)
    for c in ("pitch_type", "stand", "p_throws", "description", "events", "bb_type"):
        df[c] = df[c].astype(object).where(df[c].notna(), None)
    physics.add_physics(df)
    _io.outcomes(df)
    df["family"] = _io.family_of(df["pitch_type"])
    df["fam"] = df["family"].map(_io.FAMILY_CODE).fillna(-1).astype(np.int8)
    df["pt"] = df["pitch_type"].map(_io.PT_CODE).fillna(-1).astype(np.int8)
    df["cnt"] = _io.count_code(df["balls"], df["strikes"]).astype(np.int8)
    df["platoon"] = (df["stand"].astype(str) == df["p_throws"].astype(str)).astype(np.int8)
    df["throws_l"] = (df["p_throws"].astype(str) == "L").astype(np.int8)
    df["stand_l"] = (df["stand"].astype(str) == "L").astype(np.int8)
    df["x_away"] = (_num(df, "plate_x") * _io.away_sign(df["stand"])).astype(np.float32)
    top, bot = _num(df, "sz_top"), _num(df, "sz_bot")
    top = top.where(top.between(2.5, 4.5), 3.4)
    bot = bot.where(bot.between(0.8, 2.3), 1.6)
    df["z_rel"] = ((_num(df, "plate_z") - bot) / (top - bot)).astype(np.float32)
    z = _num(df, "zone")
    in_rule = (_num(df, "plate_x").abs() <= 0.83) & (_num(df, "plate_z") >= bot) & (_num(df, "plate_z") <= top)
    df["in_zone"] = np.where(z.notna(), z.isin(list(_io.IN_ZONE)), in_rule).astype(np.int8)
    df["spin_axis_arm"] = np.where(df["throws_l"] == 1, 360.0 - _num(df, "spin_axis"), _num(df, "spin_axis")).astype(np.float32)
    # primary fastball and differentials
    ref = fastball_refs(df)
    df = df.join(ref, on="pitcher")
    df["d_velo"] = (_num(df, "release_speed") - df["fb_velo"]).astype(np.float32)
    df["d_ivb"] = (df["ivb"] - df["fb_ivb"]).astype(np.float32)
    df["d_hb"] = (df["hb_arm"] - df["fb_hb"]).astype(np.float32)
    # previous pitch in the plate appearance
    pa = _io.pa_key(df)
    same = pa.eq(pa.shift(1)).to_numpy()
    df["has_prev"] = same.astype(np.int8)
    for c, src in (("prev_pt", "pt"),):
        df[c] = np.where(same, df[src].shift(1).fillna(-1), -1).astype(np.int8)
    df["prev_same"] = np.where(same, (df["pt"] == df["prev_pt"]).astype(float), np.nan).astype(np.float32)
    for c, src in (("d_velo_prev", "release_speed"), ("d_ivb_prev", "ivb"), ("d_hb_prev", "hb_arm")):
        v = _num(df, src)
        df[c] = np.where(same, v - v.shift(1), np.nan).astype(np.float32)
    dx, dz = df["x_dp"] - df["x_dp"].shift(1), df["z_dp"] - df["z_dp"].shift(1)
    df["dp_dist"] = np.where(same, np.sqrt(dx ** 2 + dz ** 2) * 12, np.nan).astype(np.float32)
    px, pz = _num(df, "plate_x"), _num(df, "plate_z")
    df["plate_dist"] = np.where(same, np.sqrt((px - px.shift(1)) ** 2 + (pz - pz.shift(1)) ** 2) * 12, np.nan).astype(np.float32)
    df["game_pitch"] = df.groupby(["game_pk", "pitcher"], sort=False).cumcount().astype(np.int16)
    # run value, and with in-play luck removed
    rv = _num(df, "delta_run_exp")
    df["rv"] = rv.astype(np.float32)
    xw = _num(df, "estimated_woba_using_speedangle")
    wv = _num(df, "woba_value")
    ip = df["inplay"].to_numpy() & np.isfinite(xw.to_numpy()) & np.isfinite(wv.to_numpy()) & np.isfinite(rv.to_numpy())
    b = inplay_slope
    if b is None:
        if ip.sum() > 200:
            w, r = wv.to_numpy()[ip], rv.to_numpy()[ip]
            wc = w - w.mean()
            b = float((wc * (r - r.mean())).sum() / max((wc ** 2).sum(), 1e-9))
        else:
            b = 0.8
    df.attrs["inplay_slope"] = b
    df["rv_dn"] = np.where(ip, rv + b * (xw - wv), rv).astype(np.float32)
    df["xwoba_con"] = np.where(df["inplay"], xw, np.nan).astype(np.float32)
    df = df.drop(columns=[c for c in DROP_AFTER if c in df])
    for c in df.columns:
        if df[c].dtype == np.float64:
            df[c] = df[c].astype(np.float32)
    for c in ("game_date", "stand", "p_throws"):      # low-cardinality strings: category saves ~100 MB a season
        df[c] = df[c].astype("category")
    return df


def prepared(level: str, season: int, use_cache: bool = True, path=None) -> pd.DataFrame:
    """The enriched season (cached as Parquet). Empty frame when the raw season is not on disk."""
    src = _io.pitch_path(level, season) if path is None else path
    if not src.exists():
        return pd.DataFrame()
    key = _io.file_key(PREP_VERSION, src)[:16]
    out = _io.cache_root() / "prep" / f"{level}_{season}_{key}.parquet"
    if use_cache and out.exists():
        try:
            return pd.read_parquet(out)
        except Exception:  # noqa: BLE001
            pass
    raw = _io.load_pitches(level, season, RAW_COLS, path=src)
    df = enrich(raw)
    del raw
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        for old in out.parent.glob(f"{level}_{season}_*.parquet"):
            if old != out:
                old.unlink(missing_ok=True)
        df.to_parquet(out, index=False)
    except (OSError, ValueError):
        pass
    return df


def sample_seasons(level: str, seasons: list[int], n_per_season: int, filt=None, columns: list[str] | None = None,
                   seed: int = 11, frames: dict | None = None) -> pd.DataFrame:
    """Up to n_per_season rows from each season (after `filt`), loading one season at a time. `frames`
    (season -> enriched frame) replaces disk reads (tests, synthetic)."""
    parts = []
    for i, s in enumerate(seasons):
        df = frames[s] if frames is not None and s in frames else prepared(level, s)
        if df.empty:
            continue
        if filt is not None:
            df = df[filt(df)]
        if len(df) > n_per_season:
            df = df.sample(n=n_per_season, random_state=seed + i)
        df = (df[columns] if columns else df).copy()
        df["season"] = np.int16(s)
        parts.append(df)
        del df
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
