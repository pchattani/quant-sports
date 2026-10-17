"""Synthetic stand-ins for raw MLBAM responses; no real Savant or Stats API data.

The baseball data-layer tests (tests/baseball/test_data.py) need a Baseball Savant pitch-level CSV (MLB and
Triple-A) and MLB Stats API schedule / live-feed answers. Raw MLBAM responses are never re-hosted (MLBAM terms:
individual, non-commercial, non-bulk use), so these fixtures are invented by this script:

  savant_2026-09-27.csv      200 MLB pitches, the 119-column Savant header in Savant's order and quoting
  savant_aaa_2026-09-19.csv   50 Triple-A pitches, same header, bat-tracking columns empty (as at Triple-A)
  schedule.json              a hydrated /v1/schedule answer: a regular final and a cancelled game on 27 Sep, four
                             Wild Card games on 30 Sep (team pairings and start times as in the public schedule,
                             so the ESPN scoreboard fixture maps onto them; pks, scores and people invented)
  feed_post_990841.json      /v1.1/game/{pk}/feed/live, trimmed to the fields statsapi.feed_extras reads
  feed_regular_990679.json   the same for the regular-season game

What is invented: every player and umpire id (9,000,000 and up), every name ("Player A1"), every game pk
(990xxx), every pitch value (a seeded RNG), scores, line scores, weather, ABS challenges and mound visits.
What is kept: the column / key layout of the real answers, and public facts (team ids, abbreviations, names,
venue ids and names, game-type codes, series names).

Deterministic: `python tests/baseball/fixtures/make_synthetic.py` rewrites the five files byte for byte.
The numbers asserted in test_data.py are fixed constants below (not drawn from the RNG).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).parent

# ── Savant ──────────────────────────────────────────────────────────────────

COLUMNS = [
    "pitch_type", "game_date", "release_speed", "release_pos_x", "release_pos_z", "player_name", "batter", "pitcher",
    "events", "description", "spin_dir", "spin_rate_deprecated", "break_angle_deprecated", "break_length_deprecated",
    "zone", "des", "game_type", "stand", "p_throws", "home_team", "away_team", "type", "hit_location", "bb_type",
    "balls", "strikes", "game_year", "pfx_x", "pfx_z", "plate_x", "plate_z", "on_3b", "on_2b", "on_1b", "outs_when_up",
    "inning", "inning_topbot", "hc_x", "hc_y", "tfs_deprecated", "tfs_zulu_deprecated", "umpire", "sv_id", "vx0",
    "vy0", "vz0", "ax", "ay", "az", "sz_top", "sz_bot", "hit_distance_sc", "launch_speed", "launch_angle",
    "effective_speed", "release_spin_rate", "release_extension", "game_pk", "fielder_2", "fielder_3", "fielder_4",
    "fielder_5", "fielder_6", "fielder_7", "fielder_8", "fielder_9", "release_pos_y", "estimated_ba_using_speedangle",
    "estimated_woba_using_speedangle", "woba_value", "woba_denom", "babip_value", "iso_value", "launch_speed_angle",
    "at_bat_number", "pitch_number", "pitch_name", "home_score", "away_score", "bat_score", "fld_score",
    "post_away_score", "post_home_score", "post_bat_score", "post_fld_score", "if_fielding_alignment",
    "of_fielding_alignment", "spin_axis", "delta_home_win_exp", "delta_run_exp", "bat_speed", "swing_length",
    "miss_distance", "estimated_slg_using_speedangle", "delta_pitcher_run_exp", "hyper_speed", "home_score_diff",
    "bat_score_diff", "home_win_exp", "bat_win_exp", "age_pit_legacy", "age_bat_legacy", "age_pit", "age_bat",
    "n_thruorder_pitcher", "n_priorpa_thisgame_player_at_bat", "pitcher_days_since_prev_game",
    "batter_days_since_prev_game", "pitcher_days_until_next_game", "batter_days_until_next_game",
    "api_break_z_with_gravity", "api_break_x_arm", "api_break_x_batter_in", "arm_angle", "attack_angle",
    "attack_direction", "swing_path_tilt", "intercept_ball_minus_batter_pos_x_inches",
    "intercept_ball_minus_batter_pos_y_inches",
]
# Savant quotes these columns in its CSV answer (the header is fully quoted and starts with a BOM)
QUOTED = {"pitch_type", "game_date", "release_speed", "release_pos_x", "release_pos_z", "player_name", "events",
          "description", "des", "game_type", "stand", "p_throws", "home_team", "away_team", "type", "bb_type", "pfx_x",
          "pfx_z", "inning_topbot", "launch_speed", "effective_speed", "release_extension", "release_pos_y",
          "woba_value", "pitch_name", "if_fielding_alignment", "of_fielding_alignment", "delta_home_win_exp",
          "delta_run_exp", "bat_speed", "swing_length", "miss_distance", "delta_pitcher_run_exp", "hyper_speed",
          "api_break_z_with_gravity", "api_break_x_arm", "api_break_x_batter_in", "arm_angle"}
BAT_TRACKING = {"bat_speed", "swing_length", "miss_distance", "attack_angle", "attack_direction", "swing_path_tilt",
                "intercept_ball_minus_batter_pos_x_inches", "intercept_ball_minus_batter_pos_y_inches"}

PITCHES = {  # type: (name, mph, spin, pfx_x, pfx_z)
    "FF": ("4-Seam Fastball", 95.0, 2300, -0.6, 1.3), "SI": ("Sinker", 93.5, 2150, -1.3, 0.6),
    "SL": ("Slider", 85.5, 2450, 0.4, 0.1), "CH": ("Changeup", 85.0, 1750, -1.2, 0.4),
    "CU": ("Curveball", 79.5, 2600, 0.7, -0.9), "FC": ("Cutter", 89.0, 2350, 0.2, 0.7),
}
IN_PLAY = [("single", 0.24), ("double", 0.07), ("triple", 0.01), ("home_run", 0.05), ("field_out", 0.55),
           ("force_out", 0.05), ("field_error", 0.03)]
VERB = {"single": "singles", "double": "doubles", "triple": "triples", "home_run": "homers",
        "field_out": "flies out", "force_out": "grounds into a force out", "field_error": "reaches on a fielding error",
        "walk": "walks", "strikeout": "strikes out"}
WOBA = {"single": 0.9, "double": 1.25, "triple": 1.6, "home_run": 2.0, "walk": 0.7}


class _Ids:
    """Invented MLBAM-style ids: players and umpires 9,000,001 and up."""

    def __init__(self, start: int = 9_000_001):
        self.n = start

    def __call__(self) -> int:
        self.n += 1
        return self.n - 1


def _name(code: str) -> str:
    return f"Player {code}"


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(round(v, 6))
    return str(v)


def _team(ids: _Ids, tag: str, rng: random.Random) -> dict:
    hitters = [{"id": ids(), "code": f"{tag}{k}", "stand": rng.choice("LRR")} for k in range(1, 10)]
    pitchers = [{"id": ids(), "code": f"{tag}P{k}", "throws": rng.choice("LRRR"),
                 "arsenal": rng.sample(list(PITCHES), 3), "arm": round(rng.uniform(20, 55), 1),
                 "age": rng.randint(23, 35)} for k in (1, 2)]
    return {"hitters": hitters, "pitchers": pitchers}


def _row(**kw) -> dict:
    row = dict.fromkeys(COLUMNS)
    row.update(kw)
    return row


def savant_day(day: str, games: list[tuple[str, str]], first_pk: int, rows: int, seed: int, ids: _Ids,
               bat_tracking: bool = True) -> list[dict]:
    """`rows` invented pitches spread over `games` (home, away) on `day`, game by game in order."""
    rng = random.Random(seed)
    per_game = -(-rows // len(games))
    out: list[dict] = []
    for g, (home, away) in enumerate(games):
        pk = first_pk + g
        teams = {"home": _team(ids, f"{home}H", rng), "away": _team(ids, f"{away}A", rng)}
        score = {"home": 0, "away": 0}
        nxt = {"home": 0, "away": 0}
        pas = {}
        ab = 0
        game_rows: list[dict] = []
        inning = 1
        while len(game_rows) < per_game:
            for half, bat, fld in (("Top", "away", "home"), ("Bot", "home", "away")):
                pit = teams[fld]["pitchers"][0 if inning <= 5 else 1]
                fielders = [h["id"] for h in teams[fld]["hitters"][:8]]
                outs, bases = 0, [None, None, None]
                while outs < 3 and len(game_rows) < per_game:
                    hitter = teams[bat]["hitters"][nxt[bat] % 9]
                    nxt[bat] += 1
                    ab += 1
                    pas[hitter["id"]] = pas.get(hitter["id"], 0) + 1
                    balls = strikes = 0
                    pn = 0
                    while True:
                        pn += 1
                        b0, s0 = balls, strikes                       # the count before this pitch
                        pt = rng.choice(pit["arsenal"])
                        pname, mph, spin, px, pz = PITCHES[pt]
                        r = rng.random()
                        desc = ("ball" if r < 0.36 else "called_strike" if r < 0.53 else "swinging_strike" if r < 0.64
                                else "foul" if r < 0.82 else "hit_into_play")
                        event = None
                        if desc == "ball":
                            balls += 1
                            event = "walk" if balls == 4 else None
                        elif desc in ("called_strike", "swinging_strike"):
                            strikes += 1
                            event = "strikeout" if strikes == 3 else None
                        elif desc == "foul":
                            strikes = min(strikes + 1, 2)
                        else:
                            event = rng.choices([e for e, _ in IN_PLAY], [w for _, w in IN_PLAY])[0]
                        swing = desc in ("swinging_strike", "foul", "hit_into_play")
                        row = _row(
                            pitch_type=pt, game_date=day, release_speed=round(rng.gauss(mph, 1.2), 1),
                            release_pos_x=round(rng.gauss(-1.8 if pit["throws"] == "R" else 1.8, 0.3), 2),
                            release_pos_z=round(rng.gauss(5.8, 0.2), 2),
                            player_name=f"{pit['code']}, Player", batter=hitter["id"], pitcher=pit["id"],
                            description=desc, zone=rng.randint(1, 14), game_type="R", stand=hitter["stand"],
                            p_throws=pit["throws"], home_team=home, away_team=away,
                            type="B" if desc == "ball" else "X" if desc == "hit_into_play" else "S",
                            balls=b0, strikes=s0, game_year=int(day[:4]),
                            pfx_x=round(rng.gauss(px, 0.2), 2), pfx_z=round(rng.gauss(pz, 0.2), 2),
                            plate_x=rng.gauss(0, 0.8), plate_z=rng.gauss(2.4, 0.8),
                            on_3b=bases[2], on_2b=bases[1], on_1b=bases[0], outs_when_up=outs, inning=inning,
                            inning_topbot=half, vx0=rng.gauss(5, 3), vy0=rng.gauss(-mph * 1.45, 2),
                            vz0=rng.gauss(-4, 2), ax=rng.gauss(-8, 6), ay=rng.gauss(28, 3), az=rng.gauss(-22, 7),
                            sz_top=round(rng.uniform(3.2, 3.6), 3), sz_bot=round(rng.uniform(1.5, 1.7), 3),
                            effective_speed=round(rng.gauss(mph, 1.5), 1), release_spin_rate=int(rng.gauss(spin, 80)),
                            release_extension=round(rng.uniform(5.8, 7.0), 1), game_pk=pk,
                            fielder_2=fielders[0], fielder_3=fielders[1], fielder_4=fielders[2], fielder_5=fielders[3],
                            fielder_6=fielders[4], fielder_7=fielders[5], fielder_8=fielders[6], fielder_9=fielders[7],
                            release_pos_y=round(rng.uniform(53.5, 54.7), 2), at_bat_number=ab, pitch_number=pn,
                            pitch_name=pname, home_score=score["home"], away_score=score["away"],
                            bat_score=score[bat], fld_score=score[fld],
                            if_fielding_alignment=rng.choice(["Standard", "Infield shade", "Strategic"]),
                            of_fielding_alignment="Standard", spin_axis=rng.randint(30, 330),
                            delta_run_exp=round(rng.gauss(0, 0.06), 3),
                            home_score_diff=score["home"] - score["away"], bat_score_diff=score[bat] - score[fld],
                            home_win_exp=round(rng.uniform(0.2, 0.8), 3), age_pit_legacy=pit["age"],
                            age_bat_legacy=28, age_pit=pit["age"], age_bat=rng.randint(22, 36),
                            n_thruorder_pitcher=1 + (pas[hitter["id"]] - 1) % 3,
                            n_priorpa_thisgame_player_at_bat=pas[hitter["id"]] - 1,
                            pitcher_days_since_prev_game=rng.randint(1, 6), batter_days_since_prev_game=1,
                            batter_days_until_next_game=1,
                            api_break_z_with_gravity=round(rng.uniform(1.2, 3.2), 2),
                            api_break_x_arm=round(rng.gauss(px, 0.3), 2), api_break_x_batter_in=round(rng.gauss(px, 0.3), 2),
                            arm_angle=round(rng.gauss(pit["arm"], 1.5), 1))
                        row["bat_win_exp"] = row["home_win_exp"] if bat == "home" else round(1 - row["home_win_exp"], 3)
                        row["delta_pitcher_run_exp"] = -row["delta_run_exp"]
                        row["delta_home_win_exp"] = round(rng.gauss(0, 0.02), 3)
                        if swing and bat_tracking:
                            row.update(bat_speed=round(rng.gauss(71, 4), 1), swing_length=round(rng.gauss(7.2, 0.6), 1),
                                       attack_angle=round(rng.gauss(10, 6), 1), attack_direction=round(rng.gauss(0, 12), 1),
                                       swing_path_tilt=round(rng.gauss(32, 4), 1),
                                       intercept_ball_minus_batter_pos_x_inches=rng.gauss(30, 6),
                                       intercept_ball_minus_batter_pos_y_inches=rng.gauss(25, 6))
                            if desc == "swinging_strike":
                                row["miss_distance"] = round(rng.uniform(1, 12), 1)
                        if desc == "hit_into_play":
                            ls, la = rng.gauss(89, 13), rng.gauss(12, 24)
                            bb = ("ground_ball" if la < 10 else "line_drive" if la < 25 else "fly_ball" if la < 50
                                  else "popup")
                            row.update(launch_speed=round(ls, 1), launch_angle=int(la), bb_type=bb,
                                       hit_location=rng.randint(1, 9), hc_x=round(rng.uniform(40, 210), 2),
                                       hc_y=round(rng.uniform(40, 200), 2), hit_distance_sc=max(0, int(ls * 2.2 + la * 2)),
                                       estimated_ba_using_speedangle=round(rng.uniform(0.02, 0.95), 3),
                                       estimated_woba_using_speedangle=round(rng.uniform(0.02, 1.6), 3),
                                       estimated_slg_using_speedangle=round(rng.uniform(0.02, 2.5), 3),
                                       launch_speed_angle=rng.randint(1, 6), hyper_speed=round(max(ls, 88), 1))
                        if event:
                            row["events"] = event
                            row["des"] = f"{_name(hitter['code'])} {VERB[event]}."
                            row["woba_value"] = WOBA.get(event, 0)
                            row["woba_denom"] = 1
                            if desc == "hit_into_play":
                                row["babip_value"] = int(event in ("single", "double", "triple"))
                                row["iso_value"] = {"double": 1, "triple": 2, "home_run": 3}.get(event, 0)
                            # advance runners: forced on a walk, everyone moves the hit's bases otherwise
                            if event in ("walk", "single", "field_error"):
                                runner = hitter["id"]
                                for b in range(3):
                                    runner, bases[b] = bases[b], runner
                                    if runner is None:
                                        break
                                score[bat] += runner is not None
                            elif event in ("double", "triple", "home_run"):
                                n = {"double": 2, "triple": 3, "home_run": 4}[event]
                                score[bat] += sum(x is not None for x in bases[3 - n:]) if n < 4 else sum(
                                    x is not None for x in bases) + 1
                                moved = [None, None, None]
                                for b in range(3 - n):
                                    if bases[b] is not None and b + n < 3:
                                        moved[b + n] = bases[b]
                                if n < 4:
                                    moved[n - 1] = hitter["id"]
                                bases = moved
                            elif event == "force_out":
                                outs += 1
                                bases[0] = hitter["id"]
                            else:
                                outs += 1
                        row.update(post_home_score=score["home"], post_away_score=score["away"],
                                   post_bat_score=score[bat], post_fld_score=score[fld])
                        game_rows.append(row)
                        if event or len(game_rows) >= per_game:
                            break
            inning += 1
        out += game_rows
    return out[:rows]


def write_savant(path: Path, rows: list[dict]) -> None:
    lines = [",".join(f'"{c}"' for c in COLUMNS)]
    for r in rows:
        vals = []
        for c in COLUMNS:
            s = _fmt(r[c])
            vals.append(f'"{s}"' if s and c in QUOTED else s)
        lines.append(",".join(vals))
    path.write_text("﻿" + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# ── Stats API ───────────────────────────────────────────────────────────────

TEAMS = {  # public facts: Stats API team id -> (name, abbreviation, venue id, venue name)
    "144": ("Atlanta Braves", "ATL", 4705, "Truist Park"),
    "143": ("Philadelphia Phillies", "PHI", 2681, "Citizens Bank Park"),
    "120": ("Washington Nationals", "WSH", 3309, "Nationals Park"),
    "121": ("New York Mets", "NYM", 3289, "Citi Field"),
    "147": ("New York Yankees", "NYY", 3313, "Yankee Stadium"),
    "110": ("Baltimore Orioles", "BAL", 2, "Oriole Park at Camden Yards"),
    "117": ("Houston Astros", "HOU", 2392, "Daikin Park"),
    "145": ("Chicago White Sox", "CWS", 4, "Rate Field"),
    "111": ("Boston Red Sox", "BOS", 3, "Fenway Park"),
    "135": ("San Diego Padres", "SD", 2680, "Petco Park"),
    "112": ("Chicago Cubs", "CHC", 17, "Wrigley Field"),
}
FINAL = {"abstractGameState": "Final", "codedGameState": "F", "detailedState": "Final", "statusCode": "F",
         "startTimeTBD": False, "abstractGameCode": "F"}
CANCELLED = {"abstractGameState": "Final", "codedGameState": "C", "detailedState": "Cancelled", "statusCode": "CR",
             "startTimeTBD": False, "reason": "Rain", "abstractGameCode": "F"}
POSITIONS = ["CF", "SS", "RF", "1B", "DH", "3B", "LF", "2B", "C"]

# The values test_data.py asserts (all invented)
POST_PK, REG_PK, CANCELLED_PK = 990841, 990679, 990490
POST = {"home": "144", "away": "143", "date": "2026-09-30", "start": "2026-09-30T18:00:00Z",
        "series": ("NL Wild Card Series", 2, 3),
        "innings": [(0, 1), (2, 0), (0, 0), (0, 0), (1, 0), (0, 2), (0, 0), (0, 0), (0, 0), (1, 0)],  # (away, home)
        "weather": {"condition": "Clear", "temp": "71", "wind": "7 mph, Out To CF"},
        "abs": {"away": (2, 2, 0), "home": (1, 1, 1)}, "mound": {"away": 3, "home": 2}}
REG = {"home": "120", "away": "121", "date": "2026-09-27", "start": "2026-09-27T17:05:00Z",
       "innings": [(1, 0), (0, 0), (0, 3), (0, 0), (2, 0), (0, 1), (0, 0), (1, 0), (0, 1)],
       "weather": {"condition": "Overcast", "temp": "64", "wind": "9 mph, In From LF"},
       "abs": {"away": (0, 1, 1), "home": (2, 0, 2)}, "mound": {"away": 4, "home": 1}}
CANCELLED_GAME = {"home": "147", "away": "110", "date": "2026-09-27", "start": "2026-09-27T17:05:00Z"}
OTHER_POST = [  # pk, home, away, start (UTC; the last two are evening games of 30 Sep, ET), series
    (990846, "117", "145", "2026-09-30T21:00:00Z", "AL Wild Card Series"),
    (990848, "147", "111", "2026-10-01T00:00:00Z", "AL Wild Card Series"),
    (990842, "135", "112", "2026-10-01T02:00:00Z", "NL Wild Card Series"),
]
WEATHER = [{"condition": "Sunny", "temp": "78", "wind": "5 mph, R To L"},
           {"condition": "Roof Closed", "temp": "72", "wind": "0 mph, None"},
           {"condition": "Clear", "temp": "66", "wind": "11 mph, Out To RF"}]


def _random_innings(rng: random.Random) -> list[tuple[int, int]]:
    while True:
        inns = [(rng.choice([0, 0, 0, 1, 2]), rng.choice([0, 0, 0, 1, 2])) for _ in range(9)]
        if sum(a for a, _ in inns) != sum(h for _, h in inns):
            return inns


def _ref(pid: int, kind: str = "people") -> dict:
    return {"id": pid, "fullName": _name(f"{pid % 1000:03d}"), "link": f"/api/v1/{kind}/{pid}"}


def _team_obj(tid: str) -> dict:
    name, abbr, vid, vname = TEAMS[tid]
    return {"id": int(tid), "name": name, "link": f"/api/v1/teams/{tid}", "abbreviation": abbr,
            "venue": {"id": vid, "name": vname, "link": f"/api/v1/venues/{vid}"}}


def _schedule_game(pk: int, gtype: str, spec: dict, ids: _Ids, status: dict = FINAL) -> tuple[dict, dict]:
    """A hydrated schedule game and the matching (trimmed) live feed."""
    home, away = spec["home"], spec["away"]
    vid, vname = TEAMS[home][2], TEAMS[home][3]
    final = status is FINAL
    lineups = {side: [ids() for _ in range(9)] for side in ("home", "away")} if final else None
    probables = {side: ids() for side in ("home", "away")}
    g = {
        "gamePk": pk, "link": f"/api/v1.1/game/{pk}/feed/live", "gameType": gtype, "season": spec["date"][:4],
        "gameDate": spec["start"], "officialDate": spec["date"], "status": dict(status),
        "teams": {side: {"team": _team_obj(tid), "probablePitcher": _ref(probables[side]), "splitSquad": False}
                  for side, tid in (("away", away), ("home", home))},
        "venue": {"id": vid, "name": vname, "link": f"/api/v1/venues/{vid}", "active": True, "season": spec["date"][:4]},
        "officials": [], "weather": {}, "gameNumber": 1, "publicFacing": True, "doubleHeader": "N",
        "gamedayType": "P", "tiebreaker": "N", "calendarEventID": f"14-{pk}-{spec['date']}", "seasonDisplay": spec["date"][:4],
        "dayNight": "day", "scheduledInnings": 9, "reverseHomeAwayStatus": False,
        "gamesInSeries": spec.get("series", (None, None, 3))[2], "seriesGameNumber": spec.get("series", (None, 1, None))[1],
        "seriesDescription": spec.get("series", ("Regular Season",))[0], "ifNecessary": "N",
        "ifNecessaryDescription": "Normal Game",
    }
    feed = None
    if final:
        inns = spec["innings"]
        runs = {"away": sum(a for a, _ in inns), "home": sum(h for _, h in inns)}
        for side in ("away", "home"):
            g["teams"][side].update(score=runs[side], isWinner=runs[side] > runs["home" if side == "away" else "away"])
        g["linescore"] = {
            "currentInning": len(inns), "scheduledInnings": 9,
            "innings": [{"num": k + 1, "home": {"runs": h, "hits": h + 1, "errors": 0, "leftOnBase": 1},
                         "away": {"runs": a, "hits": a + 1, "errors": 0, "leftOnBase": 1}} for k, (a, h) in enumerate(inns)],
            "teams": {side: {"runs": runs[side], "hits": runs[side] + len(inns), "errors": 0, "leftOnBase": 7,
                             "isWinner": g["teams"][side]["isWinner"]} for side in ("home", "away")},
        }
        g["decisions"] = {"winner": _ref(ids()), "loser": _ref(ids())}
        g["officials"] = [{"official": _ref(ids()), "officialType": t}
                          for t in ("Home Plate", "First Base", "Second Base", "Third Base")]
        g["weather"] = dict(spec["weather"])
        g["lineups"] = {f"{side}Players": [dict(_ref(pid), primaryPosition={"abbreviation": POSITIONS[k]})
                                           for k, pid in enumerate(lineups[side])] for side in ("home", "away")}
        if "abs" in spec:
            feed = {
                "gamePk": pk,
                "gameData": {
                    "game": {"pk": pk, "type": gtype, "doubleHeader": "N", "gameNumber": 1, "season": spec["date"][:4]},
                    "teams": {side: {"id": int(tid), "abbreviation": TEAMS[tid][1]}
                              for side, tid in (("home", home), ("away", away))},
                    "absChallenges": {"hasChallenges": True, **{
                        side: {"usedSuccessful": w, "usedFailed": l, "remaining": r}
                        for side, (w, l, r) in spec["abs"].items()}},
                    "moundVisits": {side: {"used": u, "remaining": 5 - u} for side, u in spec["mound"].items()},
                    "weather": dict(spec["weather"]), "status": dict(FINAL), "venue": {"id": vid, "name": vname},
                },
                "liveData": {
                    "boxscore": {"teams": {side: {"team": {"id": int(tid)}, "battingOrder": lineups[side]}
                                           for side, tid in (("home", home), ("away", away))}},
                    "linescore": {"teams": {side: {k: v for k, v in g["linescore"]["teams"][side].items() if k != "isWinner"}
                                            for side in ("home", "away")}},
                },
            }
    return g, feed


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    ids = _Ids()
    mlb = savant_day("2026-09-27", [("TOR", "CIN"), ("NYY", "BOS"), ("LAD", "SF")], 990101, 200, seed=27, ids=ids)
    write_savant(HERE / "savant_2026-09-27.csv", mlb)
    aaa = savant_day("2026-09-19", [("TOL", "LOU")], 990201, 50, seed=19, ids=ids, bat_tracking=False)
    write_savant(HERE / "savant_aaa_2026-09-19.csv", aaa)

    sids = _Ids(9_500_001)
    reg, reg_feed = _schedule_game(REG_PK, "R", REG, sids)
    canc, _ = _schedule_game(CANCELLED_PK, "R", CANCELLED_GAME, sids, status=CANCELLED)
    post, post_feed = _schedule_game(POST_PK, "F", POST, sids)
    rng = random.Random(30)
    more = [_schedule_game(pk, "F", {"home": h, "away": a, "date": "2026-09-30", "start": t, "series": (desc, 2, 3),
                                     "innings": _random_innings(rng), "weather": w}, sids)[0]
            for (pk, h, a, t, desc), w in zip(OTHER_POST, WEATHER)]
    write_json(HERE / "schedule.json", {"dates": [{"date": "2026-09-27", "games": [reg, canc]},
                                                  {"date": "2026-09-30", "games": [post] + more}]})
    write_json(HERE / f"feed_post_{POST_PK}.json", post_feed)
    write_json(HERE / f"feed_regular_{REG_PK}.json", reg_feed)


if __name__ == "__main__":
    main()
