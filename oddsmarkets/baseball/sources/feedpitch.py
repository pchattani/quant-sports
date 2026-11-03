"""
The pitch table of a level Baseball Savant does not publish (Double-A, High-A, Single-A), from the Stats API
live feed: one row per pitch on Savant's columns (sources/savant.py COLUMNS), so every catalogue, model and
game page reads it the way it reads MLB and Triple-A.

What the feed carries at these levels (probed 3 Nov 2026 on 2026 games):
  every park    the pitch sequence with its call, the count, base-out state, scores, batter / pitcher and hands,
                the charted pitch location (Gameday pixels, `pitchData.coordinates.x/y`) and the batter's zone
                (`strikeZoneTop/Bottom`), the batted-ball type, the scorer's hardness (soft / medium / hard), the
                fielder and the spray point (`hitData.coordinates`, Savant's hc_x / hc_y).
  tracked parks (Hawk-Eye: the Single-A Florida State League and a few others) also the 9-parameter pitch
                trajectory, velocity, spin, extension, pitch type, exit velocity, launch angle and distance.

Columns this module fills from the feed are Savant's; three are added:
  chart_x, chart_z  the charted location in feet (catcher's view, as plate_x / plate_z) at every park, from the
                    pixels by the fit in PIXEL_FIT (tracked pitches carry both). plate_x / plate_z stay the tracked
                    values only, so the location models (framing, umpires, stuff) never read a charted point.
  hardness          the scorer's soft / medium / hard on balls in play.
`zone` is Savant's 1-9 / 11-14 grid from the tracked location, else from the charted one.

Season columns (`finish_season`, on the compacted file): delta_run_exp from the level-season's own run
expectancy by base-out state and count, and wOBA / BABIP / ISO values on the PA-ending pitch.

Raw feeds are not kept: one game's rows go into its day's Parquet part (savant.write_day layout), merged with
the games already in that part.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from .. import store as st
from . import savant
from ._client import Client

logger = logging.getLogger(__name__)

API = "https://statsapi.mlb.com/api"
SOURCE = "statsapi-feed"
FEED_VERSION = "feedpitch-1"

DESC = {"B": "ball", "*B": "blocked_ball", "C": "called_strike", "S": "swinging_strike", "W": "swinging_strike_blocked",
        "F": "foul", "T": "foul_tip", "L": "foul_bunt", "M": "missed_bunt", "O": "bunt_foul_tip", "X": "hit_into_play",
        "D": "hit_into_play", "E": "hit_into_play", "H": "hit_by_pitch", "P": "pitchout", "Q": "swinging_pitchout",
        "R": "foul_pitchout", "I": "intent_ball", "V": "automatic_ball", "VB": "automatic_ball", "AB": "automatic_ball",
        "AC": "automatic_strike", "VS": "automatic_strike", "VP": "automatic_ball"}
BB_TYPE = {"ground_ball": "ground_ball", "line_drive": "line_drive", "fly_ball": "fly_ball", "popup": "popup",
           "bunt_grounder": "ground_ball", "bunt_popup": "popup", "bunt_line_drive": "line_drive"}
WOBA = {"walk": 0.69, "hit_by_pitch": 0.72, "single": 0.88, "double": 1.25, "triple": 1.58, "home_run": 2.03}
NO_DENOM = {"intent_walk", "sac_bunt", "sac_bunt_double_play", "catcher_interf"}
HIT_N = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
# Gameday pixels -> feet (catcher's view): least squares on tracked pitches, which carry both (2026 Single-A FSL and
# Triple-A feeds); see fit_pixels()
PIXEL_FIT = {"x0": 117.07, "x_per_ft": -37.49, "z0": 238.41, "z_per_ft": -26.95}
BASES = ("1B", "2B", "3B")
EXTRA_FLOAT = ("chart_x", "chart_z")
EXTRA_CAT = ("hardness",)


def feed(c: Client, gpk: str | int) -> dict | None:
    return c.get(f"{API}/v1.1/game/{gpk}/feed/live")


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _i(v: Any) -> int | None:
    x = _f(v)
    return int(round(x)) if x is not None else None


def chart_feet(x: float | None, y: float | None, fit: dict | None = None) -> tuple[float | None, float | None]:
    if x is None or y is None:
        return None, None
    p = fit or PIXEL_FIT
    return (x - p["x0"]) / p["x_per_ft"], (y - p["z0"]) / p["z_per_ft"]


def zone_of(px: float | None, pz: float | None, top: float | None, bot: float | None) -> int | None:
    """Savant's zone grid: 1-9 the strike zone in thirds (1 top left from the catcher), 11-14 the four quadrants
    outside it (11 top left, 12 top right, 13 bottom left, 14 bottom right)."""
    if px is None or pz is None:
        return None
    top = top if top and bot and top - bot > 0.8 else 3.4
    bot = bot if top and bot and top - bot > 0.8 else 1.55
    half = 17 / 24 + 0.12                           # half the plate plus a ball radius (ft)
    if -half <= px <= half and bot <= pz <= top:
        col = min(2, int((px + half) / (2 * half / 3)))
        row = min(2, int((top - pz) / ((top - bot) / 3)))
        return 1 + row * 3 + col
    mid = (top + bot) / 2
    if pz >= mid:
        return 11 if px < 0 else 12
    return 13 if px < 0 else 14


def release_point(pd_: dict) -> tuple[float | None, float | None, float | None]:
    """Release (x, y, z) at 60.5 ft minus the extension along the fitted trajectory (Savant's release_pos_*)."""
    c = pd_.get("coordinates") or {}
    ext = _f(pd_.get("extension"))
    y0, vy0, ay = _f(c.get("y0")), _f(c.get("vY0")), _f(c.get("aY"))
    if None in (y0, vy0, ay) or ext is None:
        return None, None, None
    yr = 60.5 - ext
    a, b, cc = 0.5 * ay, vy0, y0 - yr
    disc = b * b - 4 * a * cc
    if disc < 0 or a == 0:
        return None, None, None
    roots = [(-b + s * math.sqrt(disc)) / (2 * a) for s in (1, -1)]
    t = max((r for r in roots if r <= 0), default=None)
    if t is None:
        return None, None, None
    x0, vx0, ax = _f(c.get("x0")), _f(c.get("vX0")), _f(c.get("aX"))
    z0, vz0, az = _f(c.get("z0")), _f(c.get("vZ0")), _f(c.get("aZ"))
    if None in (x0, vx0, ax, z0, vz0, az):
        return None, yr, None
    return x0 + vx0 * t + 0.5 * ax * t * t, yr, z0 + vz0 * t + 0.5 * az * t * t


def _starters(box_team: dict) -> dict[int, int]:
    """{position code 1-9: player id} for the starting nine (battingOrder N00) and the starting pitcher."""
    out: dict[int, int] = {}
    for p in (box_team.get("players") or {}).values():
        bo = str(p.get("battingOrder") or "")
        if bo.isdigit() and int(bo) % 100 == 0:
            ap = p.get("allPositions") or []
            code = _i((ap[0] if ap else p.get("position") or {}).get("code"))
            if code and 1 <= code <= 9:
                out[code] = int(p["person"]["id"])
    pit = box_team.get("pitchers") or []
    if pit:
        out[1] = int(pit[0])
    return out


def rows(f: dict, abbr: dict[str, str] | None = None) -> list[dict]:
    """Savant-shaped rows for every pitch of a final game's feed (plus a pitchless row for an automatic
    intentional walk, as Savant has). `abbr` maps team ids to the store's abbreviations."""
    gd = f.get("gameData") or {}
    ld = f.get("liveData") or {}
    plays = (ld.get("plays") or {}).get("allPlays") or []
    if not plays:
        return []
    gpk = int(f.get("gamePk") or (gd.get("game") or {}).get("pk"))
    gtype = (gd.get("game") or {}).get("type")
    gdate = (gd.get("datetime") or {}).get("officialDate")
    season = _i((gd.get("game") or {}).get("season")) or _i(str(gdate)[:4])
    tms = gd.get("teams") or {}
    ab = abbr or {}

    def team_abbr(side: str) -> str | None:
        t = tms.get(side) or {}
        return ab.get(str(t.get("id"))) or t.get("abbreviation")

    home, away = team_abbr("home"), team_abbr("away")
    box = (ld.get("boxscore") or {}).get("teams") or {}
    fielders = {"home": _starters(box.get("home") or {}), "away": _starters(box.get("away") or {})}
    score = {"home": 0, "away": 0}
    bases: dict[str, int] = {}
    outs = 0
    half_key = None
    faced: dict[int, int] = {}
    out: list[dict] = []
    for pl in plays:
        about = pl.get("about") or {}
        top = bool(about.get("isTopInning"))
        inning = _i(about.get("inning")) or 0
        hk = (inning, top)
        if hk != half_key:
            half_key, bases, outs = hk, {}, 0
        bat, fld = ("away", "home") if top else ("home", "away")
        m = pl.get("matchup") or {}
        batter = _i((m.get("batter") or {}).get("id"))
        stand = (m.get("batSide") or {}).get("code")
        p_throws = (m.get("pitchHand") or {}).get("code")
        res = pl.get("result") or {}
        evs = pl.get("playEvents") or []
        runners = pl.get("runners") or []
        moves = []
        seen: set[int] = set()
        for r in runners:
            mv = r.get("movement") or {}
            d = r.get("details") or {}
            rid = _i((d.get("runner") or {}).get("id"))
            idx = _i(d.get("playIndex"))
            if rid is None:
                continue
            start = mv.get("start")
            if rid not in seen and start in BASES and bases.get(start) != rid:
                bases = {k: v for k, v in bases.items() if v != rid}
                bases[start] = rid                   # on base when the PA began (the extra-innings runner too)
            seen.add(rid)
            moves.append((idx if idx is not None else 10 ** 6, rid, start, mv.get("end"), bool(mv.get("isOut"))))
        moves.sort(key=lambda x: x[0])
        pitcher = fielders[fld].get(1) or _i((m.get("pitcher") or {}).get("id"))
        pitches = [e for e in evs if e.get("isPitch")]
        k_move = 0
        prev_count = {"balls": 0, "strikes": 0, "outs": outs}
        n_pa = faced.get(pitcher or 0, 0)
        pa_rows: list[dict] = []
        last_pitch_idx = max((_i(e.get("index")) or 0 for e in pitches), default=None)
        for e in evs:
            idx = _i(e.get("index")) or 0
            while k_move < len(moves) and moves[k_move][0] < idx:
                _apply(moves[k_move], bases, score, bat)
                k_move += 1
            det = e.get("details") or {}
            if e.get("isSubstitution"):
                code = _i((e.get("position") or {}).get("code"))
                pid = _i((e.get("player") or {}).get("id"))
                et = det.get("eventType")
                side = fld if et in ("pitching_substitution", "defensive_substitution", "defensive_switch") else None
                if side and pid and code and 1 <= code <= 9:
                    fielders[side] = {k: v for k, v in fielders[side].items() if v != pid}
                    fielders[side][code] = pid
                    if code == 1:
                        pitcher = pid
                        n_pa = faced.get(pid, 0)
            if not e.get("isPitch"):
                if e.get("count"):
                    prev_count = e["count"]
                continue
            pdat = e.get("pitchData") or {}
            co = pdat.get("coordinates") or {}
            br = pdat.get("breaks") or {}
            hd = e.get("hitData") or {}
            call = (det.get("call") or {}).get("code") or det.get("code")
            desc = DESC.get(str(call)) or str(det.get("description") or "").lower().replace(" ", "_") or None
            px, pz = _f(co.get("pX")), _f(co.get("pZ"))
            top_, bot_ = _f(pdat.get("strikeZoneTop")), _f(pdat.get("strikeZoneBottom"))
            cx, cz = chart_feet(_f(co.get("x")), _f(co.get("y")))
            zone = _i(pdat.get("zone"))
            if zone is None:
                zone = zone_of(px if px is not None else cx, pz if pz is not None else cz, top_, bot_)
            rx, _ry, rz = release_point(pdat)
            pt = det.get("type") or {}
            row = {
                "game_pk": gpk, "game_date": gdate, "game_type": gtype, "game_year": season,
                "at_bat_number": (_i(about.get("atBatIndex")) or 0) + 1, "pitch_number": _i(e.get("pitchNumber")),
                "batter": batter, "pitcher": pitcher, "stand": stand, "p_throws": p_throws,
                "home_team": home, "away_team": away, "inning": inning, "inning_topbot": "Top" if top else "Bot",
                "outs_when_up": _i(prev_count.get("outs")) if prev_count.get("outs") is not None else outs,
                "balls": _i(prev_count.get("balls")) or 0, "strikes": _i(prev_count.get("strikes")) or 0,
                "on_1b": bases.get("1B"), "on_2b": bases.get("2B"), "on_3b": bases.get("3B"),
                "description": desc, "type": "X" if det.get("isInPlay") else ("S" if det.get("isStrike") else "B"),
                "pitch_type": pt.get("code"), "pitch_name": pt.get("description"),
                "release_speed": _f(pdat.get("startSpeed")), "release_spin_rate": _f(br.get("spinRate")),
                "spin_axis": _f(br.get("spinDirection")), "release_extension": _f(pdat.get("extension")),
                "release_pos_x": rx, "release_pos_z": rz, "release_pos_y": _ry,
                "pfx_x": (-_f(br.get("breakHorizontal")) / 12.0) if _f(br.get("breakHorizontal")) is not None else None,
                "pfx_z": (_f(br.get("breakVerticalInduced")) / 12.0) if _f(br.get("breakVerticalInduced")) is not None else None,
                "plate_x": px, "plate_z": pz, "sz_top": top_, "sz_bot": bot_, "zone": zone,
                "vx0": _f(co.get("vX0")), "vy0": _f(co.get("vY0")), "vz0": _f(co.get("vZ0")),
                "ax": _f(co.get("aX")), "ay": _f(co.get("aY")), "az": _f(co.get("aZ")),
                "chart_x": cx, "chart_z": cz,
                "home_score": score["home"], "away_score": score["away"],
                "bat_score": score[bat], "fld_score": score[fld],
                "n_thruorder_pitcher": n_pa // 9 + 1,
            }
            for pos in range(2, 10):
                row[f"fielder_{pos}"] = fielders[fld].get(pos)
            if hd:
                hc = hd.get("coordinates") or {}
                row.update({"bb_type": BB_TYPE.get(str(hd.get("trajectory"))), "hit_location": _i(hd.get("location")),
                            "hc_x": _f(hc.get("coordX")), "hc_y": _f(hc.get("coordY")),
                            "launch_speed": _f(hd.get("launchSpeed")), "launch_angle": _f(hd.get("launchAngle")),
                            "hit_distance_sc": _f(hd.get("totalDistance")), "hardness": hd.get("hardness")})
            while k_move < len(moves) and moves[k_move][0] == idx:
                _apply(moves[k_move], bases, score, bat)
                k_move += 1
            row.update({"post_home_score": score["home"], "post_away_score": score["away"],
                        "post_bat_score": score[bat], "post_fld_score": score[fld]})
            if e.get("count"):
                prev_count = e["count"]
            pa_rows.append(row)
            if idx == last_pitch_idx:
                last_row = row
        while k_move < len(moves):
            _apply(moves[k_move], bases, score, bat)
            k_move += 1
        et = res.get("eventType")
        if not pitches and et == "intent_walk":
            pa_rows.append({"game_pk": gpk, "game_date": gdate, "game_type": gtype, "game_year": season,
                            "at_bat_number": (_i(about.get("atBatIndex")) or 0) + 1, "pitch_number": 1,
                            "batter": batter, "pitcher": pitcher, "stand": stand, "p_throws": p_throws,
                            "home_team": home, "away_team": away, "inning": inning,
                            "inning_topbot": "Top" if top else "Bot", "outs_when_up": outs, "balls": 0, "strikes": 0,
                            "description": "intent_ball", "type": "B",
                            "home_score": score["home"], "away_score": score["away"], "bat_score": score[bat],
                            "fld_score": score[fld], "post_home_score": score["home"],
                            "post_away_score": score["away"], "post_bat_score": score[bat],
                            "post_fld_score": score[fld], "n_thruorder_pitcher": n_pa // 9 + 1})
            last_row = pa_rows[-1]
        if pa_rows and about.get("isComplete") and et:
            last_row["events"] = et
            last_row["des"] = res.get("description")
            # the result's score is the scorer's: trust it over the runner tally where they differ
            for side, key in (("away", "awayScore"), ("home", "homeScore")):
                v = _i(res.get(key))
                if v is not None:
                    score[side] = v
            last_row.update({"post_home_score": score["home"], "post_away_score": score["away"],
                             "post_bat_score": score[bat], "post_fld_score": score[fld]})
            faced[pitcher or 0] = n_pa + 1
        out += pa_rows
        cnt = pl.get("count") or {}
        outs = _i(cnt.get("outs")) if cnt.get("outs") is not None else outs
        if outs is not None and outs >= 3:
            bases = {}
    return out


def _apply(mv: tuple, bases: dict, score: dict, bat: str) -> None:
    _idx, rid, start, end, is_out = mv
    if start in BASES and bases.get(start) == rid:
        del bases[start]
    else:
        for k in [k for k, v in bases.items() if v == rid]:
            del bases[k]
    if is_out:
        return
    if end == "score":
        score[bat] += 1
    elif end in BASES:
        bases[end] = rid


def frame(rs: list[dict]) -> pd.DataFrame:
    """Rows -> savant.typed frame (contract types; chart_x / chart_z float, hardness category)."""
    raw = pd.DataFrame(rs) if rs else pd.DataFrame(columns=savant.COLUMNS)
    for c in ("on_1b", "on_2b", "on_3b", "zone", "hit_location") + tuple(f"fielder_{p}" for p in range(2, 10)):
        if c in raw:
            raw[c] = pd.to_numeric(raw[c], errors="coerce")
    for c in EXTRA_FLOAT + EXTRA_CAT:
        if c not in raw:
            raw[c] = None
    return _extras_typed(savant.typed(raw))


def _extras_typed(df: pd.DataFrame) -> pd.DataFrame:
    """The added columns keep one type in every part (a concat of categories turns them into objects)."""
    for c in EXTRA_FLOAT:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float32") if c in df else np.float32(np.nan)
    for c in EXTRA_CAT:
        s = df[c] if c in df else pd.Series([None] * len(df), index=df.index, dtype=object)
        df[c] = s.astype("object").where(s.notna(), None).astype("string").astype("category")
    return df


# ── day parts and the season file ───────────────────────────────────────────

def write_games(level: str, season: int, day: str, df: pd.DataFrame, gpks: list[int]) -> int:
    """Replace these games' rows in the day's part (the other games of the day kept)."""
    import pyarrow.parquet as pq
    p = st.statcast_parts_dir(level, season) / f"{day}.parquet"
    old = None
    if p.exists():
        try:
            old = pq.read_table(p).to_pandas()
            old = old[~old["game_pk"].isin([int(g) for g in gpks])]
        except Exception:                                        # noqa: BLE001 - unreadable part: rewrite it
            old = None
    parts = [x for x in (old, df) if x is not None and len(x)]
    if not parts:
        savant.write_day(level, season, day, df)
        return 0
    allr = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
    savant.write_day(level, season, day, _extras_typed(allr))
    return int(len(allr))


def finish_season(level: str, season: int) -> dict:
    """Season columns on the compacted file: delta_run_exp from the season's own run expectancy by base-out
    state and count (regular season), and wOBA / BABIP / ISO values on PA-ending pitches."""
    import pyarrow.parquet as pq
    p = st.statcast_path(level, season)
    if not p.exists():
        return {"rows": 0}
    df = pq.read_table(p).to_pandas()
    df = df.sort_values(["game_pk", "at_bat_number", "pitch_number"], kind="mergesort").reset_index(drop=True)
    ev = df["events"].astype("string").fillna("")
    hit = ev.map(lambda x: HIT_N.get(x, 0)).astype(float)
    is_pa = ev.isin(set(WOBA) | set(HIT_N) | NO_DENOM | {"strikeout", "strikeout_double_play", "field_out", "force_out",
                                                         "grounded_into_double_play", "double_play", "triple_play",
                                                         "fielders_choice", "fielders_choice_out", "sac_fly",
                                                         "sac_fly_double_play", "field_error", "intent_walk"})
    df["woba_value"] = np.where(is_pa, ev.map(lambda x: WOBA.get(x, 0.0)).astype(float), np.nan).astype("float32")
    df["woba_denom"] = pd.array(np.where(is_pa, (~ev.isin(NO_DENOM)).astype(int), pd.NA), dtype="Int32")
    ab = is_pa & ~ev.isin({"walk", "intent_walk", "hit_by_pitch", "sac_fly", "sac_fly_double_play", "sac_bunt",
                           "sac_bunt_double_play", "catcher_interf"})
    bip = ab & ~ev.isin({"strikeout", "strikeout_double_play", "home_run"})
    df["babip_value"] = pd.array(np.where(bip | ev.isin({"sac_fly", "sac_fly_double_play"}),
                                          ((hit > 0) & (hit < 4)).astype(int), pd.NA), dtype="Int32")
    df["iso_value"] = pd.array(np.where(ab, np.maximum(hit - 1, 0).astype(int), pd.NA), dtype="Int32")
    re = run_values(df)
    df["delta_run_exp"] = re["delta"].astype("float32")
    tbl = savant.to_table(df)
    tmp = p.with_name(p.name + ".tmp")
    pq.write_table(tbl, tmp, compression="zstd")
    tmp.replace(p)
    tracked = float(df["release_speed"].notna().mean()) if len(df) else 0.0
    return {"rows": int(len(df)), "re_states": re["states"], "runs_per_half": re["rph"], "tracked_share": round(tracked, 4)}


def run_values(df: pd.DataFrame) -> dict:
    """Per pitch: RE(after) - RE(before) + runs on the pitch, RE by (outs, bases, balls, strikes) as the mean runs
    from that pitch to the end of the half-inning (regular season, complete halves only)."""
    n = len(df)
    if not n:
        return {"delta": pd.Series([], dtype=float), "states": 0, "rph": None}
    top = df["inning_topbot"].astype("string").fillna("").str.startswith("T").to_numpy()
    hk = df["game_pk"].to_numpy(np.int64) * 100 + df["inning"].fillna(0).to_numpy(np.int64) * 2 + (~top).astype(np.int64)
    bat0 = pd.to_numeric(df["bat_score"], errors="coerce").fillna(0).to_numpy(float)
    bat1 = pd.to_numeric(df["post_bat_score"], errors="coerce").fillna(0).to_numpy(float)
    end = pd.Series(bat1).groupby(hk).transform("max").to_numpy()
    to_end = end - bat0
    outs = np.clip(pd.to_numeric(df["outs_when_up"], errors="coerce").fillna(0).to_numpy(int), 0, 2)
    b = (df["on_1b"].notna().to_numpy().astype(int) + 2 * df["on_2b"].notna().to_numpy().astype(int)
         + 4 * df["on_3b"].notna().to_numpy().astype(int))
    balls = np.clip(pd.to_numeric(df["balls"], errors="coerce").fillna(0).to_numpy(int), 0, 3)
    strikes = np.clip(pd.to_numeric(df["strikes"], errors="coerce").fillna(0).to_numpy(int), 0, 2)
    state = ((outs * 8 + b) * 4 + balls) * 3 + strikes
    last_out = pd.Series(pd.to_numeric(df["outs_when_up"], errors="coerce").fillna(0).to_numpy()).groupby(hk).transform("max")
    complete = last_out.to_numpy() >= 2
    reg = (df["game_type"].astype("string") == "R").to_numpy() & complete
    sums = np.bincount(state[reg], weights=to_end[reg], minlength=288)
    cnts = np.bincount(state[reg], minlength=288)
    # sparse count states fall back on their base-out state's mean
    bo = state // 12
    bo_s = np.bincount(bo[reg], weights=to_end[reg], minlength=24)
    bo_n = np.bincount(bo[reg], minlength=24)
    bo_mean = np.where(bo_n > 0, bo_s / np.maximum(bo_n, 1), 0.0)
    k0 = 30.0
    re = (sums + k0 * bo_mean[np.arange(288) // 12]) / (cnts + k0)
    nxt_same = np.r_[hk[1:] == hk[:-1], False]
    re_now = re[state]
    re_next = np.where(nxt_same, np.r_[re_now[1:], 0.0], 0.0)
    delta = re_next - re_now + (bat1 - bat0)
    rph = float(pd.Series(end).groupby(hk).first().mean()) if n else None
    return {"delta": pd.Series(delta), "states": int((cnts > 0).sum()), "rph": rph}


def fit_pixels(df: pd.DataFrame) -> dict | None:
    """The pixel -> feet fit from tracked pitches (both coordinates present)."""
    ok = df["plate_x"].notna() & df["chart_x"].notna()
    if ok.sum() < 200:
        return None
    # chart_* were made with PIXEL_FIT: back to pixels, then fit
    px = df.loc[ok, "chart_x"].to_numpy(float) * PIXEL_FIT["x_per_ft"] + PIXEL_FIT["x0"]
    pz = df.loc[ok, "chart_z"].to_numpy(float) * PIXEL_FIT["z_per_ft"] + PIXEL_FIT["z0"]
    fx = np.polyfit(df.loc[ok, "plate_x"].to_numpy(float), px, 1)
    fz = np.polyfit(df.loc[ok, "plate_z"].to_numpy(float), pz, 1)
    return {"x0": float(fx[1]), "x_per_ft": float(fx[0]), "z0": float(fz[1]), "z_per_ft": float(fz[0]), "n": int(ok.sum())}
