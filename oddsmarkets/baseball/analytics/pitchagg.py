"""
One pass over a season's Statcast pitch table (one season in memory, only the columns needed): the
plate-appearance table and the per-hitter / per-pitcher / per-team counting tables every catalogue reads.

Definitions (Savant conventions unless stated)
* PA: the last pitch of a plate appearance whose `events` is a PA-ending event (hits, outs in play, walks,
  hit by pitch, strikeouts, catcher's interference); AB = PA - BB - IBB - HBP - SF - SH - CI.
* Swing, whiff (swinging strikes and foul tips), contact, called strike from `description`; in zone = Savant
  zones 1-9.
* Attack zones (Savant's scheme on normalised coordinates): u = plate_x / 0.83 ft (half the plate plus a ball
  radius), v = (plate_z - zone middle) / (half the batter's zone height); heart |u|, |v| <= 0.67; shadow
  <= 1.33 outside the heart; chase <= 2.0 outside the shadow; waste beyond.
* Batted balls: hard hit EV >= 95 mph; barrel = launch_speed_angle 6; sweet spot LA 8-32 deg; spray angle
  phi = atan2(hc_x - 125.42, 198.27 - hc_y) (deg, + toward right field), pull = phi < -15 for a right-handed
  batter (> 15 left-handed), opposite field the mirror, centre otherwise; pull-air = pulled line drives and
  fly balls.
* Expected stats (Savant's): xwOBA = (sum over balls in play of estimated_woba + woba_value of the other PA
  results) / woba_denom; xBA / xSLG likewise over at-bats.
* Velocity bands: 95+ mph, 90-95, under 90; pitch families: fastballs (FF SI FC), breaking (SL ST CU KC SV CS),
  offspeed (CH FS FO SC KN).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an

SEASON_COLS = ["game_pk", "game_date", "game_type", "at_bat_number", "pitch_number", "batter", "pitcher", "stand", "p_throws",
               "home_team", "away_team", "inning", "inning_topbot", "outs_when_up", "balls", "strikes", "on_1b", "on_2b",
               "on_3b", "pitch_type", "release_speed", "release_spin_rate", "release_extension", "release_pos_x",
               "release_pos_z", "pfx_x", "pfx_z", "plate_x", "plate_z", "sz_top", "sz_bot", "zone", "description",
               "events", "bb_type", "launch_speed", "launch_angle", "hit_distance_sc", "hc_x", "hc_y", "launch_speed_angle",
               "estimated_woba_using_speedangle", "estimated_ba_using_speedangle", "estimated_slg_using_speedangle",
               "woba_value", "woba_denom", "babip_value", "iso_value", "delta_run_exp", "delta_home_win_exp",
               "bat_score", "post_bat_score", "fielder_2", "n_thruorder_pitcher", "bat_speed", "swing_length",
               "vy0", "vz0", "ay", "az", "arm_angle"]
GAME_COLS = SEASON_COLS + ["des", "spin_axis", "vx0", "ax", "home_score", "away_score", "post_home_score", "post_away_score",
                           "home_win_exp", "attack_angle", "umpire"]
REGULAR = ("R",)
POST = ("F", "D", "L", "W", "C")
FAMILY = {"FF": "fb", "FA": "fb", "SI": "fb", "FT": "fb", "FC": "fb", "SL": "br", "ST": "br", "CU": "br", "KC": "br",
          "SV": "br", "CS": "br", "CH": "os", "FS": "os", "FO": "os", "SC": "os", "KN": "os", "EP": "os"}
FAMS = ("fb", "br", "os")
SWINGS = {"swinging_strike", "swinging_strike_blocked", "foul", "foul_tip", "hit_into_play", "foul_bunt", "missed_bunt",
          "bunt_foul_tip", "hit_into_play_no_out", "hit_into_play_score"}
WHIFFS = {"swinging_strike", "swinging_strike_blocked", "foul_tip", "missed_bunt"}
HIT = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
K_EV = {"strikeout", "strikeout_double_play"}
OUT_BIP = {"field_out", "force_out", "grounded_into_double_play", "double_play", "triple_play", "fielders_choice_out",
           "fielders_choice", "sac_fly", "sac_fly_double_play", "sac_bunt", "sac_bunt_double_play"}
PA_EVENTS = set(HIT) | OUT_BIP | {"field_error", "walk", "intent_walk", "hit_by_pitch", "catcher_interf"} | K_EV
NON_COMP = {"intent_ball", "pitchout", "automatic_strike", "automatic_ball", "swinging_pitchout"}


def load(level: str, season: int, columns: list[str] | None = None, game_types: tuple[str, ...] | None = REGULAR,
         games: list | None = None) -> pd.DataFrame:
    """One season's pitches (only `columns`; absent ones come back as NaN), categoricals kept (memory), filtered to
    `game_types` and optionally to a list of game_pks (pushed down to Parquet). Empty frame when missing."""
    p = an.pitch_path(level, season)
    cols = list(dict.fromkeys(columns or SEASON_COLS))
    if not p.exists():
        return pd.DataFrame(columns=cols)
    try:
        import pyarrow.parquet as pq
        have = set(pq.read_schema(p).names)
        want = [c for c in cols if c in have]
        filters = []
        if game_types and "game_type" in have:
            filters.append(("game_type", "in", list(game_types)))
        if games is not None:
            filters.append(("game_pk", "in", [int(g) for g in games]))
        df = pd.read_parquet(p, columns=want, filters=filters or None)
    except Exception:                                            # noqa: BLE001 - partial / unreadable file
        return pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df:
            df[c] = np.nan
    for c in ("batter", "pitcher", "game_pk", "at_bat_number", "pitch_number"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(np.int64)
    if "game_date" in df and not pd.api.types.is_datetime64_any_dtype(df["game_date"]):
        df["game_date"] = pd.to_datetime(df["game_date"].astype(str), errors="coerce")
    return df.sort_values(["game_pk", "at_bat_number", "pitch_number"], kind="mergesort").reset_index(drop=True)


def _s(df: pd.DataFrame, c: str) -> pd.Series:
    """A column as plain strings ('' for missing) without expanding the whole frame."""
    x = df[c]
    if isinstance(x.dtype, pd.CategoricalDtype):
        cats = np.asarray(x.cat.categories.astype(str), dtype=object)
        codes = x.cat.codes.to_numpy()
        out = np.where(codes >= 0, cats[np.clip(codes, 0, None)] if len(cats) else "", "")
        return pd.Series(out, index=df.index, dtype=object)
    return x.astype(object).where(x.notna(), "").astype(str)


def _f(df: pd.DataFrame, c: str) -> np.ndarray:
    return pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float) if c in df else np.full(len(df), np.nan)


def spray_angle(hc_x, hc_y) -> np.ndarray:
    return np.degrees(np.arctan2(np.asarray(hc_x, float) - 125.42, 198.27 - np.asarray(hc_y, float)))


def attack_zone(df: pd.DataFrame) -> np.ndarray:
    """0 heart, 1 shadow, 2 chase, 3 waste, -1 unknown."""
    x, z = _f(df, "plate_x"), _f(df, "plate_z")
    top, bot = _f(df, "sz_top"), _f(df, "sz_bot")
    top = np.where(np.isfinite(top) & (top - bot > 0.8), top, 3.4)
    bot = np.where(np.isfinite(bot) & (top - bot > 0.8), bot, 1.55)
    u = np.abs(x) / 0.83
    v = np.abs(z - (top + bot) / 2) / ((top - bot) / 2)
    m = np.maximum(u, v)
    out = np.where(m <= 0.67, 0, np.where(m <= 1.33, 1, np.where(m <= 2.0, 2, 3)))
    return np.where(np.isfinite(m), out, -1)


def vaa(df: pd.DataFrame) -> np.ndarray:
    """Vertical approach angle (deg, negative = descending) at the front of the plate from the 9-parameter fit."""
    vy0, vz0, ay, az = _f(df, "vy0"), _f(df, "vz0"), _f(df, "ay"), _f(df, "az")
    yf = 17.0 / 12.0
    with np.errstate(invalid="ignore", divide="ignore"):
        vyf = -np.sqrt(np.maximum(vy0 ** 2 - 2 * ay * (50.0 - yf), 0))
        t = (vyf - vy0) / ay
        vzf = vz0 + az * t
        return -np.degrees(np.arctan(vzf / vyf))


def flags(df: pd.DataFrame) -> pd.DataFrame:
    """Per-pitch numeric flags (float32) shared by every aggregation."""
    d = _s(df, "description")
    ev = _s(df, "events")
    bb = _s(df, "bb_type")
    pt = _s(df, "pitch_type")
    fam = pt.map(FAMILY).fillna("")
    zone = pd.to_numeric(df["zone"], errors="coerce").to_numpy()
    out: dict = {}
    comp = ~d.isin(NON_COMP).to_numpy()
    sw = d.isin(SWINGS).to_numpy()
    wh = d.isin(WHIFFS).to_numpy()
    inz = (zone >= 1) & (zone <= 9)
    knownz = np.isfinite(zone)
    out["pitches"] = comp.astype(np.float32)
    out["swing"] = (sw & comp).astype(np.float32)
    out["whiff"] = (wh & comp).astype(np.float32)
    out["contact"] = (sw & ~wh & comp).astype(np.float32)
    out["called"] = (d.eq("called_strike").to_numpy()).astype(np.float32)
    out["csw"] = out["called"] + out["whiff"]
    out["zone_n"] = (comp & knownz).astype(np.float32)
    out["in_zone"] = (comp & inz).astype(np.float32)
    out["out_zone"] = (comp & knownz & ~inz).astype(np.float32)
    out["z_swing"] = out["swing"] * out["in_zone"]
    out["o_swing"] = out["swing"] * out["out_zone"]
    out["z_contact"] = out["contact"] * out["in_zone"]
    out["o_contact"] = out["contact"] * out["out_zone"]
    first = (pd.to_numeric(df["pitch_number"], errors="coerce").to_numpy() == 1)
    typ_strike = d.isin({"called_strike", "foul", "foul_tip", "foul_bunt", "swinging_strike", "swinging_strike_blocked",
                         "missed_bunt", "bunt_foul_tip", "hit_into_play", "hit_into_play_no_out", "hit_into_play_score"}).to_numpy()
    out["fp"] = (first & comp).astype(np.float32)
    out["fp_swing"] = out["fp"] * out["swing"]
    out["fp_strike"] = (first & typ_strike).astype(np.float32)
    s2 = pd.to_numeric(df["strikes"], errors="coerce").to_numpy() == 2
    b = pd.to_numeric(df["balls"], errors="coerce").to_numpy()
    s = pd.to_numeric(df["strikes"], errors="coerce").to_numpy()
    out["s2_swing"] = out["swing"] * s2
    out["s2_whiff"] = out["whiff"] * s2
    rv = _f(df, "delta_run_exp")
    out["rv"] = np.nan_to_num(rv).astype(np.float32)
    az = attack_zone(df)
    for i, nm in enumerate(("heart", "shadow", "chase", "waste")):
        m = (az == i) & comp
        out[f"{nm}_n"] = m.astype(np.float32)
        out[f"{nm}_sw"] = (m & sw).astype(np.float32)
        out[f"{nm}_rv"] = np.where(m, np.nan_to_num(rv), 0).astype(np.float32)
    for f in FAMS:
        m = (fam.to_numpy() == f) & comp
        out[f"{f}_n"] = m.astype(np.float32)
        out[f"{f}_sw"] = (m & sw).astype(np.float32)
        out[f"{f}_wh"] = (m & wh).astype(np.float32)
        out[f"{f}_oz"] = (m & knownz & ~inz).astype(np.float32)
        out[f"{f}_osw"] = (m & knownz & ~inz & sw).astype(np.float32)
        out[f"{f}_rv"] = np.where(m, np.nan_to_num(rv), 0).astype(np.float32)
        out[f"{f}_csw"] = np.where(m, out["csw"], 0).astype(np.float32)
        out[f"{f}_z"] = (m & inz).astype(np.float32)
    velo = _f(df, "release_speed")
    for nm, lo, hi in (("v95", 95, 200), ("v90", 90, 95), ("vlo", 0, 90)):
        m = (velo >= lo) & (velo < hi) & comp
        out[f"{nm}_n"] = m.astype(np.float32)
        out[f"{nm}_sw"] = (m & sw).astype(np.float32)
        out[f"{nm}_wh"] = (m & wh).astype(np.float32)
    # count states for usage (pitcher)
    ahead = (s > b)
    behind = (b > s)
    for nm, m in (("ahead", ahead), ("behind", behind), ("even", b == s), ("two", s2)):
        mm = m & comp
        out[f"{nm}_n"] = mm.astype(np.float32)
        out[f"{nm}_fb"] = (mm & (fam.to_numpy() == "fb")).astype(np.float32)
        out[f"{nm}_br"] = (mm & (fam.to_numpy() == "br")).astype(np.float32)
    # bat tracking
    bs = _f(df, "bat_speed")
    ok = np.isfinite(bs) & sw & (bs >= 50)
    out["bs_n"] = ok.astype(np.float32)
    out["bs_sum"] = np.where(ok, bs, 0).astype(np.float32)
    out["fast"] = (ok & (bs >= 75)).astype(np.float32)
    sl = _f(df, "swing_length")
    okl = np.isfinite(sl) & ok
    out["sl_n"] = okl.astype(np.float32)
    out["sl_sum"] = np.where(okl, sl, 0).astype(np.float32)
    # PA-ending rows
    pa = ev.isin(PA_EVENTS).to_numpy()
    hit = ev.map(HIT).fillna(0).to_numpy(float)
    out["pa"] = pa.astype(np.float32)
    out["h"] = (hit > 0).astype(np.float32)
    for k, nm in ((1, "b1"), (2, "b2"), (3, "b3"), (4, "hr")):
        out[nm] = (hit == k).astype(np.float32)
    out["tb"] = hit.astype(np.float32)
    out["bb"] = ev.eq("walk").to_numpy().astype(np.float32)
    out["ibb"] = ev.eq("intent_walk").to_numpy().astype(np.float32)
    out["hbp"] = ev.eq("hit_by_pitch").to_numpy().astype(np.float32)
    out["k"] = ev.isin(K_EV).to_numpy().astype(np.float32)
    out["sf"] = ev.isin({"sac_fly", "sac_fly_double_play"}).to_numpy().astype(np.float32)
    out["sh"] = ev.isin({"sac_bunt", "sac_bunt_double_play"}).to_numpy().astype(np.float32)
    out["ci"] = ev.eq("catcher_interf").to_numpy().astype(np.float32)
    out["gidp"] = ev.isin({"grounded_into_double_play"}).to_numpy().astype(np.float32)
    out["roe"] = ev.eq("field_error").to_numpy().astype(np.float32)
    out["ab"] = out["pa"] - out["bb"] - out["ibb"] - out["hbp"] - out["sf"] - out["sh"] - out["ci"]
    wv = np.nan_to_num(_f(df, "woba_value"))
    wd = np.nan_to_num(_f(df, "woba_denom"))
    out["w_num"] = np.where(pa, wv, 0).astype(np.float32)
    out["w_den"] = np.where(pa, wd, 0).astype(np.float32)
    lsp = _f(df, "launch_speed")
    lan = _f(df, "launch_angle")
    bip = pa & ev.isin(set(HIT) | OUT_BIP | {"field_error"}).to_numpy() & ~ev.isin({"sac_bunt", "sac_bunt_double_play"}).to_numpy()
    xw = _f(df, "estimated_woba_using_speedangle")
    xba = _f(df, "estimated_ba_using_speedangle")
    xslg = _f(df, "estimated_slg_using_speedangle")
    has_x = bip & np.isfinite(xw)
    out["xw_num"] = np.where(has_x, xw, np.where(pa, wv, 0)).astype(np.float32)
    out["xba_num"] = np.where(has_x, xba, np.where(bip, (hit > 0).astype(float), 0)).astype(np.float32)
    out["xslg_num"] = np.where(has_x, xslg, np.where(bip, hit, 0)).astype(np.float32)
    out["xwc_n"] = has_x.astype(np.float32)
    out["xwc_sum"] = np.where(has_x, xw, 0).astype(np.float32)
    out["bip"] = bip.astype(np.float32)
    out["bip_hr0"] = (bip & (hit != 4)).astype(np.float32)
    out["bip_h0"] = (bip & (hit > 0) & (hit != 4)).astype(np.float32)
    okev = bip & np.isfinite(lsp)
    out["ev_n"] = okev.astype(np.float32)
    out["ev_sum"] = np.where(okev, lsp, 0).astype(np.float32)
    okla = bip & np.isfinite(lan)
    out["la_n"] = okla.astype(np.float32)
    out["la_sum"] = np.where(okla, lan, 0).astype(np.float32)
    out["la_sq"] = np.where(okla, lan ** 2, 0).astype(np.float32)
    out["hard"] = (okev & (lsp >= 95)).astype(np.float32)
    lsa = _f(df, "launch_speed_angle")
    for i, nm in enumerate(("weak", "topped", "under", "flare", "solid", "barrel"), start=1):
        out[nm] = (bip & (lsa == i)).astype(np.float32)
    out["lsa_n"] = (bip & np.isfinite(lsa)).astype(np.float32)
    out["sweet"] = (okla & (lan >= 8) & (lan <= 32)).astype(np.float32)
    for nm, v in (("gb", "ground_ball"), ("ld", "line_drive"), ("fbb", "fly_ball"), ("pu", "popup")):
        out[nm] = (bip & bb.eq(v).to_numpy()).astype(np.float32)
    out["bbt_n"] = out["gb"] + out["ld"] + out["fbb"] + out["pu"]
    hx, hy = _f(df, "hc_x"), _f(df, "hc_y")
    ang = spray_angle(hx, hy)
    lefty = _s(df, "stand").eq("L").to_numpy()
    pull_ang = np.where(lefty, ang, -ang)          # + = pull side
    oks = bip & np.isfinite(ang)
    out["spray_n"] = oks.astype(np.float32)
    out["pull"] = (oks & (pull_ang > 15)).astype(np.float32)
    out["oppo"] = (oks & (pull_ang < -15)).astype(np.float32)
    out["cent"] = out["spray_n"] - out["pull"] - out["oppo"]
    air = (bb.isin({"line_drive", "fly_ball"})).to_numpy()
    out["pull_air"] = (oks & (pull_ang > 15) & air).astype(np.float32)
    out["oppo_air"] = (oks & (pull_ang < -15) & air).astype(np.float32)
    dist = _f(df, "hit_distance_sc")
    hrd = (hit == 4) & np.isfinite(dist)
    out["hr_dist_n"] = hrd.astype(np.float32)
    out["hr_dist_sum"] = np.where(hrd, dist, 0).astype(np.float32)
    fbd = bip & bb.eq("fly_ball").to_numpy() & np.isfinite(dist)
    out["fb_dist_n"] = fbd.astype(np.float32)
    out["fb_dist_sum"] = np.where(fbd, dist, 0).astype(np.float32)
    out["hr_fb"] = (bip & bb.eq("fly_ball").to_numpy() & (hit == 4)).astype(np.float32)
    # PA results by velocity band and family of the PA-ending pitch
    for nm, lo, hi in (("v95", 95, 200), ("v90", 90, 95), ("vlo", 0, 90)):
        m = pa & (velo >= lo) & (velo < hi)
        out[f"{nm}_xw"] = np.where(m, out["xw_num"], 0).astype(np.float32)
        out[f"{nm}_den"] = np.where(m, wd, 0).astype(np.float32)
    for f in FAMS:
        m = pa & (fam.to_numpy() == f)
        out[f"{f}_xw"] = np.where(m, out["xw_num"], 0).astype(np.float32)
        out[f"{f}_den"] = np.where(m, wd, 0).astype(np.float32)
    # platoon (hitter side: v the pitcher's hand; pitcher side: v the batter's hand), on PA-ending rows
    pth = _s(df, "p_throws").to_numpy()
    st = _s(df, "stand").to_numpy()
    for side, arr in (("vlhp", pth == "L"), ("vrhp", pth == "R"), ("vlhb", st == "L"), ("vrhb", st == "R")):
        m = pa & arr
        out[f"{side}_pa"] = m.astype(np.float32)
        out[f"{side}_wn"] = np.where(m, wv, 0).astype(np.float32)
        out[f"{side}_wd"] = np.where(m, wd, 0).astype(np.float32)
        out[f"{side}_xn"] = np.where(m, out["xw_num"], 0).astype(np.float32)
        out[f"{side}_k"] = np.where(m, out["k"], 0).astype(np.float32)
        mp = comp & arr
        out[f"{side}_n"] = mp.astype(np.float32)
        out[f"{side}_fb"] = (mp & (fam.to_numpy() == "fb")).astype(np.float32)
        out[f"{side}_br"] = (mp & (fam.to_numpy() == "br")).astype(np.float32)
        out[f"{side}_os"] = (mp & (fam.to_numpy() == "os")).astype(np.float32)
    # pitch shape sums (model-free arsenal: velocity, spin, IVB, arm-side HB, extension, VAA, release height)
    okv = comp & np.isfinite(velo)
    out["velo_n"] = okv.astype(np.float32)
    out["velo_sum"] = np.where(okv, velo, 0).astype(np.float32)
    arm = np.where(pth == "L", 1.0, -1.0)
    for nm, arr in (("spin", _f(df, "release_spin_rate")), ("ivb", _f(df, "pfx_z") * 12), ("hb", _f(df, "pfx_x") * 12 * arm),
                    ("ext", _f(df, "release_extension")), ("vaa", vaa(df)), ("relz", _f(df, "release_pos_z")),
                    ("rels", _f(df, "release_pos_x") * arm)):
        ok = comp & np.isfinite(arr)
        out[f"{nm}_n"] = ok.astype(np.float32)
        out[f"{nm}_sum"] = np.where(ok, arr, 0).astype(np.float32)
    out["pitches_all"] = np.ones(len(df), np.float32)
    return pd.DataFrame(out, index=df.index)


def team_of(df: pd.DataFrame, side: str = "bat") -> pd.Series:
    """The batting (or fielding) team abbreviation of each pitch."""
    top = _s(df, "inning_topbot").str.lower().str.startswith("t").to_numpy()
    h, a = _s(df, "home_team").to_numpy(), _s(df, "away_team").to_numpy()
    if side == "bat":
        return pd.Series(np.where(top, a, h), index=df.index)
    return pd.Series(np.where(top, h, a), index=df.index)


def aggregate(df: pd.DataFrame, fl: pd.DataFrame, by: str | pd.Series) -> pd.DataFrame:
    key = df[by] if isinstance(by, str) else by
    g = fl.groupby(key.to_numpy(), sort=False).sum()
    g.index = g.index.map(lambda x: str(x))
    return g


def extras(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Per entity: games, EV90 / max EV / max distance on balls in play, last team, mean release values."""
    ev = _s(df, "events")
    bip = ev.isin(set(HIT) | OUT_BIP | {"field_error"}).to_numpy()
    lsp = _f(df, "launch_speed")
    key = df[by].astype(str)
    out = pd.DataFrame({"games": df.groupby(key)["game_pk"].nunique()})
    b = pd.DataFrame({"k": key[bip].to_numpy(), "ev": lsp[bip]})
    b = b[np.isfinite(b["ev"])]
    if len(b):
        gb = b.groupby("k")["ev"]
        out["ev90"] = gb.quantile(0.9)
        out["ev_max"] = gb.max()
    dist = _f(df, "hit_distance_sc")
    d2 = pd.DataFrame({"k": key[bip].to_numpy(), "d": dist[bip]})
    d2 = d2[np.isfinite(d2["d"])]
    if len(d2):
        out["dist_max"] = d2.groupby("k")["d"].max()
    return out


def pa_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per completed plate appearance: ids, teams, date, inning/half, outs recorded, runs scored during
    it (post_bat_score at the last pitch minus bat_score at the first), the result and its run value."""
    if not len(df):
        return pd.DataFrame()
    g = df.groupby(["game_pk", "at_bat_number"], sort=False)
    first = g.head(1).set_index(["game_pk", "at_bat_number"])
    last = g.tail(1).set_index(["game_pk", "at_bat_number"])
    out = pd.DataFrame(index=first.index)
    for c in ("game_date", "batter", "pitcher", "stand", "p_throws", "inning", "inning_topbot", "outs_when_up", "bat_score",
              "home_team", "away_team", "n_thruorder_pitcher"):
        out[c] = first[c]
    out["events"] = _s(last.reset_index(), "events").to_numpy()
    out["post_bat_score"] = pd.to_numeric(last["post_bat_score"], errors="coerce")
    out["woba_value"] = pd.to_numeric(last["woba_value"], errors="coerce")
    out["woba_denom"] = pd.to_numeric(last["woba_denom"], errors="coerce")
    out["rv_pa"] = g["delta_run_exp"].sum(min_count=1)
    out["wpa_savant"] = g["delta_home_win_exp"].sum(min_count=1)
    out["n_pitches"] = g.size()
    out = out.reset_index()
    out["runs"] = (out["post_bat_score"] - pd.to_numeric(out["bat_score"], errors="coerce")).clip(lower=0).fillna(0)
    out["half"] = np.where(_s(out, "inning_topbot").str.lower().str.startswith("t"), 0, 1)
    out["hkey"] = out["game_pk"].astype(np.int64) * 100 + pd.to_numeric(out["inning"], errors="coerce").fillna(0).astype(int) * 2 + out["half"]
    nxt_outs = out["outs_when_up"].shift(-1)
    same = out["hkey"].shift(-1) == out["hkey"]
    o0 = pd.to_numeric(out["outs_when_up"], errors="coerce").fillna(0)
    out["outs_rec"] = np.where(same, pd.to_numeric(nxt_outs, errors="coerce").fillna(3) - o0, 3 - o0).clip(0, 3)
    out["is_pa"] = out["events"].isin(PA_EVENTS)
    out["bat_team"] = np.where(out["half"] == 0, _s(out, "away_team"), _s(out, "home_team"))
    out["fld_team"] = np.where(out["half"] == 0, _s(out, "home_team"), _s(out, "away_team"))
    return out


def pitcher_lines(pa: pd.DataFrame) -> pd.DataFrame:
    """Per pitcher: games, starts (first pitcher of his team's half-innings in inning 1), outs, runs, batters faced,
    pitches."""
    if not len(pa):
        return pd.DataFrame()
    key = pa["pitcher"].astype(str)
    g = pa.groupby(key)
    out = pd.DataFrame({"g": g["game_pk"].nunique(), "outs": g["outs_rec"].sum(), "runs": g["runs"].sum(),
                        "bf": g["is_pa"].sum(), "np": g["n_pitches"].sum()})
    firsts = pa.sort_values(["game_pk", "half", "at_bat_number"]).drop_duplicates(["game_pk", "half"])
    out["gs"] = firsts["pitcher"].astype(str).value_counts().reindex(out.index).fillna(0)
    return out


def last_team(df: pd.DataFrame, by: str, side: str) -> pd.Series:
    """The team (abbreviation) of each player's most recent pitch. The frame is sorted by game_pk (load), which is not
    date order (a gamePk is assigned when the schedule is made; a make-up game keeps its early pk), so the rows are
    put in date order first: without that a traded player was shown on whichever club he faced in his highest gamePk."""
    t = team_of(df, side)
    d = pd.DataFrame({"k": df[by].astype(str).to_numpy(), "t": t.to_numpy()})
    if "game_date" in df:
        d["d"] = pd.to_datetime(df["game_date"], errors="coerce").to_numpy()
        d["pk"] = pd.to_numeric(df["game_pk"], errors="coerce").to_numpy()
        d["ab"] = pd.to_numeric(df["at_bat_number"], errors="coerce").to_numpy() if "at_bat_number" in df else 0
        d = d.sort_values(["d", "pk", "ab"], kind="mergesort", na_position="first")
    return d.groupby("k")["t"].last()
