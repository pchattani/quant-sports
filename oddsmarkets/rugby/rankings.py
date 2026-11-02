"""
Our replica of the World Rugby men's rankings, rebuilt from results with the published points-exchange formula.
World Rugby's own feeds are not used (their terms limit the content to personal use); the formula is public and
quoted on Wikipedia ("World Rugby Rankings", How to calculate the Points Exchange, read 2 Nov 2026):

  A, B   the two teams' pre-match ratings; before 1 July 2026 the home team's A is raised by 3 for the calculation
         (home advantage, none at a neutral venue). From 1 July 2026 there is no home allowance.
  D      A - B, capped at +-10
  win    the winner gains (10 - D_w) / 10, where D_w is the winner's rating minus the loser's (capped at +-10), so
         between 0 (a favourite beating an outsider 10+ points below) and 2; the loser drops the same
  draw   the favourite gives D / 10 to the underdog (0 to 1)
  margin a win by more than 15 points multiplies the exchange by 1.5
  weight Rugby World Cup matches double the exchange
  new    a new member starts on 30.00 (40.00 before 1 December 2012), provisional for its first ten tests

This module is pure: `Ranker.update(match)` applies one result, `exchange(...)` is the formula, `what_if(...)` lists
the rating change of every possible result band for an upcoming match (the "what each result would do" view).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

HOME_BONUS = 3.0
HOME_BONUS_ENDS = "2026-07-01"          # World Rugby removed the home allowance from 1 July 2026
NEW_MEMBER_SWITCH = "2012-12-01"


def _cap(x: float, lo: float = -10.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


def exchange(a: float, b: float, margin: int, home: str | None, when: str, world_cup: bool = False) -> float:
    """Points team A gains (B loses the same) for a result with `margin` = A's score minus B's.

    home: "a", "b" or None (neutral). when: ISO date (decides the home allowance)."""
    ra, rb = a, b
    if home and str(when)[:10] < HOME_BONUS_ENDS:
        if home == "a":
            ra += HOME_BONUS
        elif home == "b":
            rb += HOME_BONUS
    d = _cap(ra - rb)
    if margin > 0:
        x = 1.0 - d / 10.0
    elif margin < 0:
        x = -(1.0 + d / 10.0)
    else:
        x = -d / 10.0
    if abs(margin) > 15:
        x *= 1.5
    if world_cup:
        x *= 2.0
    return x


def start_points(when: str) -> float:
    return 40.0 if str(when)[:10] < NEW_MEMBER_SWITCH else 30.0


@dataclass
class Ranker:
    """Rolls the ratings forward match by match. `seed` maps team id -> starting points (teams not in it start on
    `default(team, when)`). History keeps (date, team, points) after each match for the movement charts."""
    seed: dict = field(default_factory=dict)
    default: object = None
    points: dict = field(default_factory=dict)
    played: dict = field(default_factory=dict)
    last: dict = field(default_factory=dict)
    history: list = field(default_factory=list)

    def get(self, team: str, when: str) -> float:
        if team not in self.points:
            if team in self.seed:
                self.points[team] = float(self.seed[team])
            elif callable(self.default):
                self.points[team] = float(self.default(team, when))
            else:
                self.points[team] = start_points(when)
        return self.points[team]

    def update(self, home: str, away: str, hs: int, as_: int, when: str, neutral: bool = False,
               world_cup: bool = False) -> float:
        a, b = self.get(home, when), self.get(away, when)
        x = exchange(a, b, int(hs) - int(as_), None if neutral else "a", when, world_cup)
        self.points[home] = a + x
        self.points[away] = b - x
        for t in (home, away):
            self.played[t] = self.played.get(t, 0) + 1
            self.last[t] = str(when)[:10]
        self.history.append((str(when)[:10], home, round(self.points[home], 4), away, round(self.points[away], 4), round(x, 4)))
        return x

    def table(self, active_since: str | None = None) -> list[tuple[str, float]]:
        rows = [(t, p) for t, p in self.points.items() if not active_since or self.last.get(t, "") >= active_since]
        return sorted(rows, key=lambda r: -r[1])


def what_if(a: float, b: float, home: str | None, when: str, world_cup: bool = False) -> list[dict]:
    """For an upcoming match between A and B: the change to A's points (B's is the opposite) for each result band."""
    out = []
    for label, m in (("A by 16+", 20), ("A by 1-15", 5), ("Draw", 0), ("B by 1-15", -5), ("B by 16+", -20)):
        x = exchange(a, b, m, home, when, world_cup)
        out.append({"result": label, "margin": m, "a": round(x, 2), "b": round(-x, 2),
                    "a_after": round(a + x, 2), "b_after": round(b - x, 2)})
    return out


def today_iso() -> str:
    return date.today().isoformat()
