"""
Synthetic NFL seasons for builder B's tests and for development before real data is on disk.

`simulate_season` plays a small league game by game, drive by drive and play by play with planted truth,
and returns frames shaped like nflverse's releases (pbp column names, participation and FTN charting keyed
the same way). `write_season` writes them to the raw root in builder A's layout
(`<raw>/raw/pbp/play_by_play_<season>.parquet`, `pbp_participation_<season>.parquet`,
`ftn_charting_<season>.parquet`, `nextgen_stats/ngs_rushing.parquet`, `schedules/games.parquet`).

Planted effects (the `truth` dict records them):
* completion: logit cp = CP0 - CP_AIR * air_yards + qb_skill - CP_PRESSURE * pressure - CP_DEF * def_q;
  receivers drop a planted share of catchable balls;
* rushing: yards ~ RUN0 + rusher_skill - RUN_BOX * (box - 7) + 0.5 * (off_q - def_q) + noise;
* field goals: logit p = FG0 - FG_DIST * (distance - 40) + kicker_skill + FG_ALT * (altitude > 0)
  - FG_WIND * wind / 10 (outdoors);
* yards after catch: mean YAC0 - YAC_AIR * air_yards + receiver_yac (exponential);
* coaches: go-for-it propensity on 4th down shifted by `aggr` (planted ranking);
* team quality moves every play (off_q, def_q) and the pregame spread is the expected margin.
nflfastR-style columns (ep, wp, epa, cp, cpoe, xyac_mean_yardage, vegas_wp) are crude closed forms so the
comparison code paths run; they are not meant to be good.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import numpy as np
import pandas as pd

CP0, CP_AIR, CP_PRESSURE, CP_DEF = 1.7, 0.085, 0.7, 0.25
RUN0, RUN_BOX = 4.3, 0.9
FG0, FG_DIST, FG_ALT, FG_WIND = 1.35, 0.11, 0.35, 0.15
YAC0, YAC_AIR = 5.5, 0.12
HFA = 2.0
TEAMS = ["DEN", "KC", "BUF", "MIA", "DAL", "PHI", "SF", "SEA", "GB", "CHI", "BAL", "PIT"]
ROOFS = {"DEN": "outdoors", "KC": "outdoors", "BUF": "outdoors", "MIA": "outdoors", "DAL": "closed", "PHI": "outdoors",
         "SF": "outdoors", "SEA": "outdoors", "GB": "outdoors", "CHI": "outdoors", "BAL": "outdoors", "PIT": "outdoors"}


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def make_league(rng: random.Random, n_teams: int = 8, season: int = 2024) -> dict:
    teams = {}
    for i, t in enumerate(TEAMS[:n_teams]):
        pid = lambda k, j: f"00-{season % 100:02d}{i:02d}{k}{j:02d}"   # noqa: E731 - small local id helper
        teams[t] = {
            "off_q": rng.gauss(0, 1.0), "def_q": rng.gauss(0, 1.0),
            "qb": pid(1, 0), "qb_skill": rng.gauss(0, 0.45),
            "rbs": [pid(2, j) for j in range(2)], "rb_skill": [rng.gauss(0, 0.9) for _ in range(2)],
            "wrs": [pid(3, j) for j in range(4)], "wr_yac": [rng.gauss(0, 1.2) for _ in range(4)],
            "wr_drop": [min(0.25, max(0.0, rng.gauss(0.07, 0.04))) for _ in range(4)],
            "ol": [pid(4, j) for j in range(6)],
            "k": pid(5, 0), "k_skill": rng.gauss(0, 0.45), "p": pid(6, 0), "p_skill": rng.gauss(0, 3.0),
            "coach": f"Coach {t}", "aggr": [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5][i % 6],
        }
    return teams


class _Game:
    """One game's state machine (attributes only; no closures over arrays)."""

    def __init__(self, rng, season, week, home, away, teams, gid):
        self.rng, self.season, self.week = rng, season, week
        self.home, self.away, self.T, self.gid = home, away, teams, gid
        th, ta = teams[home], teams[away]
        q = 3.0 * (th["off_q"] - ta["def_q"]) - 3.0 * (ta["off_q"] - th["def_q"]) + 6.0 * (th["qb_skill"] - ta["qb_skill"])
        self.spread_line = round((HFA + q) * 2) / 2
        self.roof = ROOFS.get(home, "outdoors")
        self.temp = None if self.roof != "outdoors" else round(rng.gauss(55, 15))
        self.wind = None if self.roof != "outdoors" else max(0, round(rng.gauss(8, 5)))
        self.score = {home: 0, away: 0}
        self.to = {home: 3, away: 3}
        self.rows, self.part, self.ftn = [], [], []
        self.play_id = 1
        self.opening_receiver = home if rng.random() < 0.5 else away
        self.home_opening_kickoff = 1 if self.opening_receiver == home else 0    # nflverse: 1 = home received

    def other(self, t):
        return self.away if t == self.home else self.home

    # ------------------------------------------------------------------ rows
    def add(self, pos, gsr, down, togo, yl, ptype, **kw):
        d = self.other(pos)
        qtr = min(4, int((3600 - gsr) // 900) + 1) if gsr > 0 else 4
        hsr = gsr - 1800 if gsr > 1800 else gsr
        row = {"game_id": self.gid, "play_id": self.play_id, "season": self.season, "week": self.week,
               "season_type": "REG", "home_team": self.home, "away_team": self.away, "posteam": pos, "defteam": d,
               "posteam_type": "home" if pos == self.home else "away", "qtr": qtr, "down": down,
               "ydstogo": togo, "goal_to_go": int(down is not None and togo >= yl), "yardline_100": yl,
               "half_seconds_remaining": max(0, hsr), "game_seconds_remaining": max(0, gsr),
               "score_differential": self.score[pos] - self.score[d], "posteam_score": self.score[pos],
               "defteam_score": self.score[d], "posteam_timeouts_remaining": self.to[pos],
               "defteam_timeouts_remaining": self.to[d], "home_opening_kickoff": self.home_opening_kickoff,
               "roof": self.roof, "temp": self.temp, "wind": self.wind, "play_type": ptype,
               "spread_line": self.spread_line, "home_coach": self.T[self.home]["coach"],
               "away_coach": self.T[self.away]["coach"]}
        row.update(kw)
        self.rows.append(row)
        self.play_id += 1
        return row

    # ------------------------------------------------------------------ plays
    def scrimmage(self, pos, gsr, down, togo, yl):
        """Returns (yards, turnover, row) for a pass or run."""
        r, t, o = self.rng, self.T[pos], self.T[self.other(pos)]
        late_behind = gsr < 900 and self.score[pos] < self.score[self.other(pos)]
        p_pass = 0.56 + (0.2 if late_behind else 0) + (0.1 if togo >= 7 else 0) - (0.2 if togo <= 2 else 0)
        rushers = 5 if r.random() < 0.3 else 4
        if r.random() < p_pass:
            pressure = 1 if r.random() < (0.26 + 0.08 * (rushers - 4) + 0.05 * o["def_q"] - 0.04 * t["off_q"]) else 0
            if r.random() < (0.03 + 0.12 * pressure):
                yards = -int(r.uniform(3, 10))
                row = self.add(pos, gsr, down, togo, yl, "pass", pass_attempt=1, sack=1, qb_dropback=1,
                               passer_player_id=t["qb"], yards_gained=yards, qb_hit=1)
                self._part(row, 6, rushers, pressure, t)
                self._ftn(row, 6, rushers, pressure=pressure, sack=1)
                return yards, False, row
            if r.random() < 0.15:
                air = r.randint(-4, 1)
            else:
                air = int(min(max(1, r.gammavariate(2.0, 4.6)), 55))
            air = min(air, yl)
            j = r.randrange(4)
            loc = r.choice(["left", "middle", "right"])
            cp = _sig(CP0 - CP_AIR * air + t["qb_skill"] - CP_PRESSURE * pressure - CP_DEF * o["def_q"])
            p_int = 0.012 + 0.0008 * max(air, 0) + 0.01 * pressure - 0.01 * t["qb_skill"]
            u = r.random()
            catchable = u < cp / max(1e-9, 1 - t["wr_drop"][j])
            drop = 0
            if u < p_int:
                comp, inter = 0, 1
            else:
                inter = 0
                comp = 1 if (r.random() < cp) else 0
                if not comp and r.random() < t["wr_drop"][j] * 1.5:
                    drop = 1
            yac = 0
            if comp:
                m = max(1.0, YAC0 - YAC_AIR * air + t["wr_yac"][j] + 0.3 * t["off_q"])
                yac = int(r.expovariate(1.0 / m))
                yac = min(yac, yl - air)
            yards = air + yac if comp else 0
            row = self.add(pos, gsr, down, togo, yl, "pass", pass_attempt=1, sack=0, qb_dropback=1,
                           complete_pass=comp, incomplete_pass=int(not comp and not inter), interception=inter,
                           air_yards=air, yards_after_catch=yac if comp else None, yards_gained=yards,
                           pass_location=loc, pass_length="deep" if air >= 15 else "short",
                           passer_player_id=t["qb"], receiver_player_id=t["wrs"][j],
                           qb_hit=int(pressure and r.random() < 0.5),
                           cp=_sig(1.5 - 0.08 * air), _cp_true=cp)
            row["cpoe"] = 100 * (comp - row["cp"]) if not inter else None
            row["xyac_mean_yardage"] = max(0.0, 5.0 - 0.1 * air) if comp else None
            self._part(row, 6, rushers, pressure, t)
            self._ftn(row, 6, rushers, pressure=pressure, drop=drop, int_worthy=int(inter or r.random() < 0.01),
                      catchable=int(catchable))
            return yards, bool(inter), row
        box = 8 if togo <= 2 else (6 if togo >= 8 else 7)
        box += r.choice([-1, 0, 0, 1])
        j = 0 if r.random() < 0.7 else 1
        mu = RUN0 + t["rb_skill"][j] - RUN_BOX * (box - 7) + 0.5 * (t["off_q"] - o["def_q"])
        yards = int(round(r.gauss(mu, 4.5)))
        if r.random() < 0.04:
            yards += int(r.expovariate(1 / 15.0))
        yards = min(yards, yl)
        fum = r.random() < 0.006
        loc = r.choice(["left", "middle", "right"])
        row = self.add(pos, gsr, down, togo, yl, "run", rush_attempt=1, rushing_yards=yards, yards_gained=yards,
                       rusher_player_id=t["rbs"][j], run_location=loc,
                       run_gap=None if loc == "middle" else r.choice(["end", "tackle", "guard"]), fumble_lost=int(fum),
                       _ryoe_true_mu=mu)
        self._part(row, box, 4, 0, t)
        self._ftn(row, box, 4)
        return yards, fum, row

    def _part(self, row, box, rushers, pressure, t):
        ol = self.rng.sample(t["ol"], 5)
        onf = [t["qb"], t["rbs"][0], *t["wrs"][:3], *ol]
        cov = self.rng.choice(["COVER_1", "COVER_2", "COVER_3", "COVER_4", "COVER_6"])
        self.part.append({"nflverse_game_id": self.gid, "play_id": row["play_id"], "defenders_in_box": box,
                          "number_of_pass_rushers": rushers if row["play_type"] == "pass" else None,
                          "was_pressure": bool(pressure) if row["play_type"] == "pass" else None,
                          "time_to_throw": round(self.rng.uniform(2.2, 3.4), 2) if row["play_type"] == "pass" else None,
                          "offense_players": ";".join(onf), "defense_players": "",
                          "defense_coverage_type": cov, "defense_man_zone_type":
                              "MAN_COVERAGE" if cov in ("COVER_0", "COVER_1") else "ZONE_COVERAGE",
                          "offense_formation": "SHOTGUN", "offense_personnel": "1 RB, 1 TE, 3 WR"})

    def _ftn(self, row, box, rushers, pressure=0, drop=0, int_worthy=0, catchable=None, sack=0):
        self.ftn.append({"nflverse_game_id": self.gid, "nflverse_play_id": row["play_id"], "n_defense_box": box,
                         "n_pass_rushers": rushers, "n_blitzers": max(0, rushers - 4), "is_drop": bool(drop),
                         "is_interception_worthy": bool(int_worthy), "is_qb_out_of_pocket": bool(pressure and self.rng.random() < 0.4),
                         "is_play_action": self.rng.random() < 0.2, "is_screen_pass": (row.get("air_yards") or 1) <= 0,
                         "is_throw_away": False, "is_catchable_ball": None if catchable is None else bool(catchable),
                         "is_qb_fault_sack": bool(sack and self.rng.random() < 0.2)})

    # ------------------------------------------------------------------ game loop
    def play(self):
        r = self.rng
        gsr = 3600
        pos = self.opening_receiver
        yl = 75
        self.add(self.other(pos), gsr, None, 0, 35, "kickoff")
        self.rows[-1]["posteam"] = pos
        self.rows[-1]["defteam"] = self.other(pos)
        down, togo = 1, 10
        half = 1
        while True:
            if half == 1 and gsr <= 1800:
                half = 2
                gsr = 1800
                self.to = {self.home: 3, self.away: 3}
                pos = self.other(self.opening_receiver)
                self.add(self.opening_receiver, gsr, None, 0, 35, "kickoff")
                self.rows[-1]["posteam"], self.rows[-1]["defteam"] = pos, self.opening_receiver
                yl, down, togo = 75, 1, 10
            if gsr <= 0:
                break
            dt = r.randint(24, 42)
            if gsr < 300 and r.random() < 0.05 and self.to[pos] > 0:
                self.to[pos] -= 1
            if down == 4:
                kind = self.fourth_choice(pos, gsr, togo, yl)
                if kind == "punt":
                    tq = self.T[pos]
                    net = int(r.gauss(41 + tq["p_skill"], 7))
                    tb = yl - net <= 0
                    opp_yl = 80 if tb else 100 - (yl - net)
                    opp_yl = min(99, max(1, opp_yl))
                    self.add(pos, gsr, 4, togo, yl, "punt", punter_player_id=tq["p"], kick_distance=net + 6,
                             return_yards=6 if not tb else 0, touchback=int(tb), _punt_opp_yl=opp_yl)
                    gsr -= 8
                    pos, yl, down, togo = self.other(pos), opp_yl, 1, 10
                    continue
                if kind == "fg":
                    self.field_goal(pos, gsr, togo, yl)
                    gsr -= 5
                    made = self.rows[-1]["field_goal_result"] == "made"
                    if made:
                        pos = self.other(pos)
                        self.add(self.other(pos), gsr, None, 0, 35, "kickoff")
                        self.rows[-1]["posteam"], self.rows[-1]["defteam"] = pos, self.other(pos)
                        yl, down, togo = 75, 1, 10
                    else:
                        pos, yl, down, togo = self.other(pos), min(80, 100 - (yl + 7)), 1, 10
                    continue
            yards, turnover, row = self.scrimmage(pos, gsr, down, togo, yl)
            gsr -= dt
            if row["play_type"] == "pass" and not row.get("complete_pass") and not row.get("sack"):
                gsr += dt - 6
            new_yl = yl - yards
            if turnover:
                pos, yl, down, togo = self.other(pos), min(99, max(1, 100 - new_yl)), 1, 10
                continue
            if new_yl <= 0:
                row["touchdown"], row["td_team"] = 1, pos
                row["first_down"] = 1
                if down >= 3:
                    row["third_down_converted" if down == 3 else "fourth_down_converted"] = 1
                self.score[pos] += 6
                self.after_td(pos, gsr)
                pos = self.other(pos)
                self.add(self.other(pos), gsr, None, 0, 35, "kickoff")
                self.rows[-1]["posteam"], self.rows[-1]["defteam"] = pos, self.other(pos)
                yl, down, togo = 75, 1, 10
                continue
            if new_yl >= 100:
                row["safety"] = 1
                self.score[self.other(pos)] += 2
                pos, yl, down, togo = self.other(pos), 60, 1, 10
                continue
            if yards >= togo:
                row["first_down"] = 1
                if down == 3:
                    row["third_down_converted"] = 1
                if down == 4:
                    row["fourth_down_converted"] = 1
                yl, down, togo = new_yl, 1, min(10, new_yl)
            else:
                if down == 3:
                    row["third_down_failed"] = 1
                if down == 4:
                    row["fourth_down_failed"] = 1
                    pos, yl, down, togo = self.other(pos), 100 - new_yl, 1, 10
                    continue
                yl, down, togo = new_yl, down + 1, togo - yards
        res = self.score[self.home] - self.score[self.away]
        for row in self.rows:
            row["result"] = res
        return res

    def fourth_choice(self, pos, gsr, togo, yl):
        r, t = self.rng, self.T[pos]
        behind = self.score[self.other(pos)] - self.score[pos]
        base = -1.2 - 0.45 * (togo - 1) - 0.02 * max(0, yl - 40) + 0.7 * t["aggr"]
        if gsr < 600 and behind > 0:
            base += 2.5
        if r.random() < _sig(base):
            return "go"
        if yl + 17 <= 55:
            return "fg"
        return "punt"

    def field_goal(self, pos, gsr, togo, yl):
        t = self.T[pos]
        dist = yl + 17
        alt = 1.0 if self.home == "DEN" else 0.0
        wind = (self.wind or 0) if self.roof == "outdoors" else 0
        p = _sig(FG0 - FG_DIST * (dist - 40) + t["k_skill"] + FG_ALT * alt - FG_WIND * wind / 10.0)
        made = self.rng.random() < p
        if made:
            self.score[pos] += 3
        self.add(pos, gsr, 4, togo, yl, "field_goal", kicker_player_id=t["k"], kick_distance=dist,
                 field_goal_result="made" if made else "missed", _fg_true=p)

    def after_td(self, pos, gsr):
        r, t = self.rng, self.T[pos]
        behind = self.score[self.other(pos)] - self.score[pos]
        go2 = r.random() < (0.5 if (gsr < 600 and behind in (2, 5, 9, 10)) else 0.04)
        if go2:
            ok = r.random() < 0.48
            if ok:
                self.score[pos] += 2
            self.add(pos, gsr, None, 2, 2, "pass", two_point_attempt=1,
                     two_point_conv_result="success" if ok else "failure")
        else:
            ok = r.random() < _sig(2.8 + t["k_skill"])
            if ok:
                self.score[pos] += 1
            self.add(pos, gsr, None, 0, 15, "extra_point", kicker_player_id=t["k"], kick_distance=33,
                     extra_point_result="good" if ok else "failed")


def _crude_nflfastr(df: pd.DataFrame) -> pd.DataFrame:
    """Crude stand-ins for nflfastR's ep / wp / epa (not models)."""
    yl = df["yardline_100"].astype(float)
    dn = df["down"].astype(float).fillna(1)
    df["ep"] = 6.0 - 0.075 * yl - 0.45 * (dn - 1) - 0.03 * df["ydstogo"].astype(float)
    nxt = df.groupby("game_id")["ep"].shift(-1)
    same = df.groupby("game_id")["posteam"].shift(-1) == df["posteam"]
    after = np.where(same, nxt, -nxt)
    after = np.where(df.get("touchdown", 0) == 1, 7.0, after)
    df["epa"] = np.nan_to_num(after - df["ep"])
    gsr = df["game_seconds_remaining"].astype(float).clip(lower=1)
    pos_sp = np.where(df["posteam"] == df["home_team"], df["spread_line"], -df["spread_line"])
    z = (df["score_differential"] + pos_sp * gsr / 3600) / (13.5 * np.sqrt(gsr / 3600) + 1.5)
    df["wp"] = 1 / (1 + np.exp(-1.6 * z))
    df["vegas_wp"] = df["wp"]
    return df


def simulate_season(season: int = 2024, n_teams: int = 8, rounds: int = 4, seed: int = 0,
                    teams: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """(pbp, participation, ftn, schedules, truth). Each pair of teams meets `rounds` times (home and away
    alternating), so n_games = rounds * n_teams * (n_teams - 1) / 2."""
    rng = random.Random(seed * 1000 + season)
    T = teams or make_league(rng, n_teams, season)
    names = list(T)
    rows, part, ftn, sched = [], [], [], []
    week = 1
    gnum = 0
    for rd in range(rounds):
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                h, a = (names[i], names[j]) if (rd + i + j) % 2 == 0 else (names[j], names[i])
                gid = f"{season}_{week:02d}_{a}_{h}_{gnum}"
                g = _Game(rng, season, week, h, a, T, gid)
                res = g.play()
                rows.extend(g.rows)
                part.extend(g.part)
                ftn.extend(g.ftn)
                sched.append({"game_id": gid, "season": season, "game_type": "REG", "week": week, "home_team": h,
                              "away_team": a, "home_score": g.score[h], "away_score": g.score[a], "result": res,
                              "spread_line": g.spread_line, "roof": g.roof, "temp": g.temp, "wind": g.wind,
                              "home_coach": T[h]["coach"], "away_coach": T[a]["coach"]})
                gnum += 1
                if gnum % max(1, len(names) // 2) == 0:
                    week = min(18, week + 1)
    pbp = pd.DataFrame(rows)
    for c in ("touchdown", "safety", "first_down", "third_down_converted", "fourth_down_converted",
              "fourth_down_failed", "complete_pass", "interception", "sack", "pass_attempt", "rush_attempt",
              "qb_dropback", "fumble_lost", "two_point_attempt", "qb_hit", "touchback", "incomplete_pass"):
        if c not in pbp:
            pbp[c] = 0
        pbp[c] = pbp[c].fillna(0).astype(int)
    for c in ("td_team", "field_goal_result", "two_point_conv_result", "extra_point_result", "pass_location",
              "run_location", "run_gap", "passer_player_id", "receiver_player_id", "rusher_player_id",
              "kicker_player_id", "punter_player_id", "pass_length"):
        if c not in pbp:
            pbp[c] = None
    pbp["qb_scramble"] = 0
    pbp["qb_kneel"] = 0
    pbp["qb_spike"] = 0
    pbp["penalty"] = 0
    pbp = _crude_nflfastr(pbp)
    truth = {"teams": T, "season": season}
    return pbp, pd.DataFrame(part), pd.DataFrame(ftn), pd.DataFrame(sched), truth


def write_season(raw: Path, season: int = 2024, seed: int = 0, n_teams: int = 8, rounds: int = 4,
                 teams: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Simulate and write one season in builder A's raw layout. Returns (pbp with truth columns, truth)."""
    raw = Path(raw)
    pbp, part, ftn, sched, truth = simulate_season(season, n_teams, rounds, seed, teams)
    out = pbp[[c for c in pbp.columns if not c.startswith("_")]]
    (raw / "raw" / "pbp").mkdir(parents=True, exist_ok=True)
    out.to_parquet(raw / "raw" / "pbp" / f"play_by_play_{season}.parquet", index=False)
    if 2016 <= season <= 2025:
        (raw / "raw" / "pbp_participation").mkdir(parents=True, exist_ok=True)
        part.to_parquet(raw / "raw" / "pbp_participation" / f"pbp_participation_{season}.parquet", index=False)
    if season >= 2022:
        (raw / "raw" / "ftn_charting").mkdir(parents=True, exist_ok=True)
        ftn.to_parquet(raw / "raw" / "ftn_charting" / f"ftn_charting_{season}.parquet", index=False)
    # NGS rushing: a truth-based RYOE per rusher (NGS's own model is tracking-based)
    ngs_rows = []
    for t, v in truth["teams"].items():
        for pid, sk in zip(v["rbs"], v["rb_skill"]):
            ngs_rows.append({"season": season, "season_type": "REG", "week": 0, "player_gsis_id": pid,
                             "team_abbr": t, "rush_yards_over_expected_per_att": sk + 0.3 * v["off_q"]})
    nd = raw / "raw" / "nextgen_stats"
    nd.mkdir(parents=True, exist_ok=True)
    np_ = nd / "ngs_rushing.parquet"
    ngs = pd.DataFrame(ngs_rows)
    if np_.exists():
        old = pd.read_parquet(np_)
        ngs = pd.concat([old[old["season"] != season], ngs], ignore_index=True)
    ngs.to_parquet(np_, index=False)
    sd = raw / "raw" / "schedules"
    sd.mkdir(parents=True, exist_ok=True)
    sp = sd / "games.parquet"
    if sp.exists():
        old = pd.read_parquet(sp)
        sched = pd.concat([old[old["season"] != season], sched], ignore_index=True)
    sched.to_parquet(sp, index=False)
    return pbp, truth
