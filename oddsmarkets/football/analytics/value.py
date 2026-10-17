"""
Player value for The Quant Footballer: goals added (GA), goals above replacement
(GAR) and points above replacement (PAR).

The currency is expected goal difference. Each player-match line in the stores
(Sofascore's per-match statistics) is turned into counts of sixteen actions:
non-penalty xG, xA, key passes, progressive carries, dribbles, accurate passes in
the opposition half, possession lost, tackles won, interceptions, blocks,
clearances, recoveries (the six out-of-possession actions scaled by 50 /
opponent possession, as the site's PAdj metrics are), aerials won, errors leading
to a shot, and for goalkeepers goals prevented and claims/sweeps.

The weights that turn counts into goals are fitted, not chosen: a ridge
regression with sign constraints (more of a good action never lowers value)
predicts each match's non-penalty xG difference from the two line-ups' *prior*
per-90 rates (each player's rates from his matches before that day, shrunk to his
position's mean over 450 minutes), weighted by the minutes each player then
played. Fitted walk-forward, the same model is scored on matches it has not
seen against the same line-ups' prior Sofascore ratings, and against each team's
own prior xG difference (`validate`). The final weights are fitted on every club
match.

A player's goals added per 90 is then the weighted sum of his rates. Raw values
are relative to the competition's own opposition, so each competition is centred
on its mean and moved by its strength on the pooled Dixon-Coles scale (the mean
expected goal difference of its clubs against the pool-average club, shared over
eleven players). Goals above replacement subtract the replacement level of the
player's role (the 20th percentile of regulars in that role); points above
replacement convert goals to points with the Poisson slope of expected points on
goal difference at the competition's scoring rate.

Roles come from the line-ups: Sofascore lists each line of a starting XI right to
left in formation order, so the formation string ("4-2-3-1") assigns GK, CB, FB,
DM, CM, AM, W and ST to the starters (`formation_roles`). Substitutes take the
role they usually start in, else Sofascore's G/D/M/F.

Everything here is pure computation over the stores and the built payloads, so it
runs offline and is tested on synthetic stores.
"""
from __future__ import annotations

import logging
import math
from array import array
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import numpy as np

logger = logging.getLogger(__name__)

PEN_XG = 0.79

# (key, label, component, sign, possession-adjusted, side)
FEATURES: tuple[tuple[str, str, str, int, bool, str], ...] = (
    ("npxg", "Non-penalty xG", "Shooting", 1, False, "att"),
    ("xa", "Expected assists", "Creating", 1, False, "att"),
    ("kp", "Key passes", "Creating", 1, False, "att"),
    ("prog", "Progressive carries", "Progression", 1, False, "att"),
    ("drb", "Dribbles completed", "Progression", 1, False, "att"),
    ("ohp", "Accurate passes in the opposition half", "Passing", 1, False, "att"),
    ("lost", "Possession lost (fewer is better)", "Ball security", -1, False, "att"),
    ("tkw", "Tackles won (possession-adjusted)", "Defending", 1, True, "def"),
    ("int", "Interceptions (possession-adjusted)", "Defending", 1, True, "def"),
    ("blk", "Blocks (possession-adjusted)", "Defending", 1, True, "def"),
    ("clr", "Clearances (possession-adjusted)", "Defending", 1, True, "def"),
    ("rec", "Recoveries (possession-adjusted)", "Defending", 1, True, "def"),
    ("aer", "Aerial duels won", "Aerial", 1, False, "def"),
    ("err", "Errors leading to a shot (fewer is better)", "Defending", -1, False, "def"),
    ("gp", "Goals prevented (goalkeepers)", "Goalkeeping", 1, False, "def"),
    ("gkc", "High claims and sweeper actions (goalkeepers)", "Goalkeeping", 1, False, "def"),
)
FKEYS = tuple(f[0] for f in FEATURES)
NF = len(FEATURES)

# Per-line counts the fantasy layer scores (fantasy.py), collected in the same pass over the
# stores: goals, assists, xG (penalties included), xA, saves, own goals, penalties missed,
# yellow and red cards (from the incidents; a second yellow counts as a red only), the FPL
# 2025/26 defensive-contribution counts (clearances + blocks + interceptions + tackles, and
# the same plus recoveries), and goals conceded while on the pitch (from the goal incidents'
# minutes and the line's minutes; the side's goals against x minutes / 90 without incidents).
FANTASY_KEYS = ("g", "a", "xg", "xa", "sv", "og", "pm", "yc", "rc", "cbit", "cbirt", "gc")
NFF = len(FANTASY_KEYS)
COMPONENTS = ("Shooting", "Creating", "Progression", "Passing", "Ball security", "Defending", "Aerial", "Goalkeeping")
COMP_OF = np.array([COMPONENTS.index(f[2]) for f in FEATURES])
# The display adds two more components: Sofascore's match rating (the second stage of
# the model) and the competition's centring and strength.
COMPONENTS_OUT = COMPONENTS + ("Rating", "League")
RATING_BASE = 6.0               # the rating input is (rating - 6.0) per 90; the constant cancels in the centring

ROLES = ("GK", "CB", "FB", "DM", "CM", "AM", "W", "ST")
ROLE_LABELS = {"GK": "Goalkeeper", "CB": "Centre-back", "FB": "Full-back / wing-back", "DM": "Defensive midfielder",
               "CM": "Central midfielder", "AM": "Attacking midfielder", "W": "Winger", "ST": "Striker",
               "DF": "Defender", "MF": "Midfielder", "FW": "Forward"}
LETTER_ROLE = {"G": "GK", "D": "DF", "M": "MF", "F": "FW"}
LETTERS = ("G", "D", "M", "F")
# Club units: what the club page grades.
UNITS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("GK", "Goalkeeper", ("GK",)),
    ("CB", "Centre-backs", ("CB",)),
    ("FB", "Full-backs and wing-backs", ("FB",)),
    ("MID", "Central and defensive midfield", ("DM", "CM")),
    ("ATT", "Attacking midfield and wingers", ("AM", "W")),
    ("ST", "Strikers", ("ST",)),
)
UNIT_OF = {r: u for u, _, rs in UNITS for r in rs}
# A coarse role (from Sofascore's letter) falls into a unit and into fine roles for replacement.
COARSE_UNIT = {"GK": "GK", "DF": "CB", "MF": "MID", "FW": "ST"}
COARSE_FINE = {"GK": ("GK",), "DF": ("CB", "FB"), "MF": ("DM", "CM", "AM"), "FW": ("W", "ST")}

# Shrinkage and floors.
PRIOR_MINUTES = 450.0          # prior rates: position mean worth this many minutes
PROJ_MINUTES = 900.0           # projected value: replacement level worth this many minutes
REGULAR_MINUTES = 900          # a "regular" for replacement levels and the 12-month percentiles
REPLACEMENT_PCT = 20           # replacement level: this percentile of regulars in the role
WINDOW_DAYS = 365
MIN_FIT_MATCHES = 300          # below this the default weights are used
FVI_MINUTES = 2500.0           # a regular's season for the fair value index
FVI_YEARS = 4
FVI_DISCOUNT = 0.85
BIG_FIVE = ("premier-league", "la-liga", "serie-a", "bundesliga", "ligue-1")
LEAGUE_TIERS = {
    "premier-league": "Top five (Europe)", "la-liga": "Top five (Europe)", "serie-a": "Top five (Europe)",
    "bundesliga": "Top five (Europe)", "ligue-1": "Top five (Europe)",
    "eredivisie": "Other Europe", "primeira-liga": "Other Europe", "belgian-pro-league": "Other Europe",
    "brasileirao": "South America", "liga-argentina": "South America",
    "mls": "North America", "liga-mx": "North America", "saudi-pro-league": "Asia",
}

# Weights fitted on the stores of 15 October 2026 (6,0xx club matches); used only when a
# build has too few matches to fit its own (offline tests, a fresh clone). Goals of xG
# difference per unit of each action (per action, so per-90 rates multiply them).
DEFAULT_BETA = {
    "npxg": 0.5, "xa": 0.3, "kp": 0.01, "prog": 0.005, "drb": 0.01, "ohp": 0.002, "lost": 0.002,
    "tkw": 0.005, "int": 0.005, "blk": 0.005, "clr": 0.002, "rec": 0.002, "aer": 0.003, "err": 0.02,
    "gp": 0.3, "gkc": 0.01,
}
DEFAULT_RATING_W = 0.1

# Typical registration periods (month, day) per league: approximate, the exact dates
# are set every year by each association. Used only for the "window open/closed" note.
WINDOWS: dict[str, list[tuple[tuple[int, int], tuple[int, int]]]] = {
    "premier-league": [((6, 16), (9, 1)), ((1, 1), (2, 2))],
    "la-liga": [((7, 1), (9, 1)), ((1, 2), (2, 2))],
    "serie-a": [((7, 1), (9, 1)), ((1, 2), (2, 2))],
    "bundesliga": [((7, 1), (9, 1)), ((1, 1), (2, 2))],
    "ligue-1": [((6, 16), (9, 1)), ((1, 1), (2, 2))],
    "eredivisie": [((7, 1), (9, 1)), ((1, 1), (2, 2))],
    "primeira-liga": [((7, 1), (9, 1)), ((1, 2), (2, 2))],
    "belgian-pro-league": [((6, 10), (9, 6)), ((1, 1), (2, 2))],
    "saudi-pro-league": [((7, 1), (9, 8)), ((1, 1), (2, 2))],
    "brasileirao": [((1, 6), (4, 7)), ((7, 10), (9, 2))],
    "liga-argentina": [((1, 1), (3, 15)), ((7, 1), (8, 31))],
    "mls": [((1, 30), (4, 23)), ((7, 24), (8, 21))],
    "liga-mx": [((6, 1), (9, 1)), ((12, 1), (2, 1))],
}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _f(v) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def _r(v, n: int = 3):
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, n) if math.isfinite(x) else None


# ── roles from formations ────────────────────────────────────────────────────

def formation_roles(lines: list[int]) -> list[str] | None:
    """
    Roles of the ten outfield starters, in Sofascore's order (each line right to
    left, defence first), for a formation such as [4, 2, 3, 1]. None when the
    formation does not have ten outfielders.
    """
    if not lines or sum(lines) != 10 or any(n <= 0 for n in lines) or len(lines) < 2:
        return None
    d, a, mids = lines[0], lines[-1], lines[1:-1]
    out: list[str] = []
    if d >= 5:
        out += ["FB"] + ["CB"] * (d - 2) + ["FB"]
    elif d == 4:
        out += ["FB", "CB", "CB", "FB"]
    else:
        out += ["CB"] * d
    wide = d >= 4
    k = len(mids)
    for i, n in enumerate(mids):
        deepest, advanced = i == 0, (i == k - 1 and k >= 2)
        if n >= 4:
            outer = "W" if wide else "FB"
            out += [outer] + ["CM"] * (n - 2) + [outer]
            wide = True
        elif n == 3:
            out += ["W", "AM", "W"] if advanced else ["CM", "CM", "CM"]
            if advanced:
                wide = True
        elif n == 2:
            out += ["DM", "DM"] if (deepest and k >= 2) else (["AM", "AM"] if advanced else ["CM", "CM"])
        else:
            out += ["DM"] if (deepest and k >= 2) else (["AM"] if advanced else ["CM"])
    if a == 1:
        out += ["ST"]
    elif a == 2:
        out += ["ST", "ST"]
    elif a == 3:
        out += ["W", "ST", "W"]
    else:
        out += ["W"] + ["ST"] * (a - 2) + ["W"]
    return out if len(out) == 10 else None


def assign_roles(formation: str | None, letters: list[str | None]) -> list[str | None] | None:
    """Roles for a starting XI in source order (`letters` are Sofascore's G/D/M/F), or None."""
    if not formation or len(letters) != 11:
        return None
    try:
        lines = [int(x) for x in str(formation).split("-")]
    except ValueError:
        return None
    roles = formation_roles(lines)
    if roles is None:
        return None
    gk = [i for i, l in enumerate(letters) if l == "G"]
    if len(gk) != 1:
        return None
    out: list[str | None] = []
    it = iter(roles)
    for i in range(11):
        out.append("GK" if i == gk[0] else next(it))
    return out


# ── incidents: goal timeline and cards ──────────────────────────────────────

def _minute(inc: dict) -> float:
    """An incident's minute as a number: 45+2 is 45.02, 90+3 is 90.03 (ordered, inside its half)."""
    t = _f(inc.get("time"))
    add = _f(inc.get("added_time"))
    return t + min(add, 30.0) / 100.0


def goal_timeline(incidents: list) -> list[tuple[float, int]] | None:
    """
    [(minute, side that scored: 0 home, 1 away)] from a match's goal incidents, in order,
    read from the running score so own goals count for the right side. None when the
    match has no incidents at all (the caller then shares the goals against over minutes).
    """
    if not incidents:
        return None
    goals = [i for i in incidents if isinstance(i, dict) and str(i.get("incident_type") or "") == "goal"
             and i.get("home_score") is not None and i.get("away_score") is not None]
    goals.sort(key=lambda i: (_minute(i), _f(i.get("home_score")) + _f(i.get("away_score"))))
    out: list[tuple[float, int]] = []
    h0 = a0 = 0
    for i in goals:
        h, a = int(_f(i.get("home_score"))), int(_f(i.get("away_score")))
        if h > h0:
            out.append((_minute(i), 0))
        elif a > a0:
            out.append((_minute(i), 1))
        h0, a0 = max(h, h0), max(a, a0)
    return out


def card_counts(incidents: list) -> dict[str, tuple[int, int]]:
    """player id -> (yellow cards, red cards); a second yellow counts as a red and not as a yellow too."""
    out: dict[str, list[int]] = {}
    for i in incidents or []:
        if not isinstance(i, dict) or str(i.get("incident_type") or "") != "card" or i.get("player_id") is None:
            continue
        c = out.setdefault(str(i["player_id"]), [0, 0])
        cls = str(i.get("incident_class") or "").lower()
        if cls == "yellow":
            c[0] += 1
        elif cls in ("red", "yellowred"):
            c[1] = 1
            if cls == "yellowred":
                c[0] = max(c[0] - 1, 0)
    return {k: (v[0], v[1]) for k, v in out.items()}


# ── collecting the per-match lines ───────────────────────────────────────────

@dataclass
class Rows:
    """Every player-match line with minutes, as arrays (one entry per line)."""

    pid: np.ndarray
    match: np.ndarray       # index into the match table
    side: np.ndarray        # 0 home, 1 away
    day: np.ndarray         # date ordinal
    comp: np.ndarray        # index into comps
    sid: np.ndarray         # index into sids
    tid: np.ndarray         # the player's team id (-1 unknown)
    start: np.ndarray
    mins: np.ndarray
    letter: np.ndarray      # index into LETTERS, -1 unknown
    role: np.ndarray        # index into ROLES, -1 when the line-up gives none
    rating: np.ndarray      # nan when missing
    X: np.ndarray           # (n, NF) signed counts
    comps: list[str]
    comp_scope: list[str]
    sids: list[str]
    current: dict[str, str]                 # comp -> current season key
    m_day: np.ndarray
    m_comp: np.ndarray
    m_tid: np.ndarray                       # (n_matches, 2) home, away team ids
    m_npxg: np.ndarray                      # (n_matches, 2)
    m_goals: np.ndarray                     # (n_matches, 2)
    m_gid: np.ndarray
    F: np.ndarray | None = None              # (n, NFF) fantasy counts, FANTASY_KEYS order (None when not collected)

    def __len__(self) -> int:
        return int(self.pid.size)


class ValueCollector:
    """Accumulates the line-ups of every store, one store at a time (memory: compact arrays)."""

    def __init__(self) -> None:
        self.comps: list[str] = []
        self.comp_scope: list[str] = []
        self.sids: list[str] = []
        self._sid_ix: dict[str, int] = {}
        self.current: dict[str, str] = {}
        self._ints = {k: array("q") for k in ("pid", "match", "side", "day", "comp", "sid", "tid", "start", "letter", "role")}
        self._mins = array("f")
        self._rating = array("f")
        self._X = array("f")
        self._F = array("f")
        self._m = {k: array("q") for k in ("gid", "day", "comp", "th", "ta", "gh", "ga")}
        self._mx = array("f")
        self._seen: set[str] = set()

    def _sid(self, key: str) -> int:
        ix = self._sid_ix.get(key)
        if ix is None:
            ix = self._sid_ix[key] = len(self.sids)
            self.sids.append(key)
        return ix

    def add_store(self, slug: str, store: dict, scope: str = "club", season_key: Callable[[dict], Any] | None = None,
                  current_key: Any = None) -> int:
        """One competition's store. Returns the number of matches added."""
        matches = store.get("matches") or {}
        lineups = store.get("lineups") or {}
        if not lineups:
            return 0
        if slug in self.comps:
            ci = self.comps.index(slug)
        else:
            ci = len(self.comps)
            self.comps.append(slug)
            self.comp_scope.append(scope)
        meta = store.get("meta") or {}
        key_of = season_key or (lambda m: m.get("season_id"))
        if current_key is None:
            current_key = meta.get("season_id")
        if current_key is not None:
            self.current[slug] = str(current_key)
        extras = store.get("lineup_extras") or {}
        sheets = store.get("team_stats") or {}
        incidents = store.get("incidents") or {}
        added = 0
        for gid in sorted(lineups, key=lambda g: str((matches.get(str(g)) or {}).get("date") or "")):
            lu = lineups.get(gid)
            m = matches.get(str(gid))
            if not isinstance(lu, dict) or not isinstance(m, dict) or str(gid) in self._seen:
                continue
            if m.get("hs") is None or m.get("as") is None or not m.get("date"):
                continue
            try:
                day = date.fromisoformat(str(m["date"])[:10]).toordinal()
            except ValueError:
                continue
            k = key_of(m)
            if k is None:
                continue
            si = self._sid(str(k))
            pens: dict[str, int] = {}
            for inc in incidents.get(str(gid)) or []:
                if isinstance(inc, dict) and str(inc.get("incident_type") or "").lower() == "goal" and \
                        str(inc.get("incident_class") or "").lower() == "penalty" and inc.get("player_id") is not None:
                    pens[str(inc["player_id"])] = pens.get(str(inc["player_id"]), 0) + 1
            form = (extras.get(str(gid)) or {}).get("formation") or {}
            sheet = sheets.get(str(gid)) or {}
            match_inc = incidents.get(str(gid)) or []
            timeline = goal_timeline(match_inc)
            cards = card_counts(match_inc)
            sub_on = {str(i.get("player_id")): _minute(i) for i in match_inc
                      if isinstance(i, dict) and str(i.get("incident_type") or "") == "substitution" and i.get("player_id") is not None}
            conceded_side = (int(m["as"]), int(m["hs"]))
            mi = len(self._m["gid"])
            npxg_side = [0.0, 0.0]
            n_rows = 0
            for side_i, side in enumerate(("home", "away")):
                team = m.get(side)
                tid = m.get(f"{side}_id")
                plist = [(str(pid), p) for pid, p in lu.items() if isinstance(p, dict) and p.get("t") == team]
                if not plist:
                    continue
                starters = [(pid, p) for pid, p in plist if not p.get("sub")]
                roles = assign_roles(form.get(side), [p.get("p") for _, p in starters])
                role_of = {pid: r for (pid, _), r in zip(starters, roles)} if roles else {}
                own = (sheet.get(side) or {}).get("ballPossession") if sheet else None
                opp_poss = 100.0 - min(max(_f(own), 25.0), 75.0) if own is not None else 50.0
                padj = 50.0 / opp_poss
                for pid, p in plist:
                    s = p.get("s") or {}
                    mins = _f(s.get("minutesPlayed"))
                    if mins <= 0:
                        continue
                    letter = p.get("p")
                    is_g = letter == "G"
                    xg = _f(s.get("expectedGoals"))
                    npxg = max(xg - PEN_XG * (pens.get(pid, 0) + _f(s.get("penaltyMiss"))), 0.0)
                    npxg_side[side_i] += npxg
                    x = (
                        npxg, _f(s.get("expectedAssists")), _f(s.get("keyPass")),
                        _f(s.get("progressiveBallCarriesCount")), _f(s.get("wonContest")),
                        _f(s.get("accurateOppositionHalfPasses")), -_f(s.get("possessionLostCtrl")),
                        _f(s.get("wonTackle")) * padj, _f(s.get("interceptionWon")) * padj,
                        _f(s.get("outfielderBlock")) * padj, _f(s.get("totalClearance")) * padj,
                        _f(s.get("ballRecovery")) * padj, _f(s.get("aerialWon")),
                        -(_f(s.get("errorLeadToAShot")) + _f(s.get("errorLeadToAGoal"))),
                        _f(s.get("goalsPrevented")) if is_g else 0.0,
                        (_f(s.get("goodHighClaim")) + _f(s.get("accurateKeeperSweeper"))) if is_g else 0.0,
                    )
                    try:
                        pid_i = int(pid)
                    except ValueError:
                        continue
                    self._ints["pid"].append(pid_i)
                    self._ints["match"].append(mi)
                    self._ints["side"].append(side_i)
                    self._ints["day"].append(day)
                    self._ints["comp"].append(ci)
                    self._ints["sid"].append(si)
                    self._ints["tid"].append(int(tid) if tid is not None else -1)
                    self._ints["start"].append(0 if p.get("sub") else 1)
                    self._ints["letter"].append(LETTERS.index(letter) if letter in LETTERS else -1)
                    r = role_of.get(pid)
                    self._ints["role"].append(ROLES.index(r) if r in ROLES else -1)
                    self._mins.append(mins)
                    rt = s.get("rating")
                    self._rating.append(_f(rt) if rt is not None and _f(rt) > 0 else float("nan"))
                    self._X.extend(x)
                    yc, rc = cards.get(pid, (0, 0))
                    if timeline is not None:
                        on = sub_on.get(pid, 90.0 - mins) if p.get("sub") else 0.0
                        off = 999.0 if (not p.get("sub") and mins >= 89) else (on + mins if p.get("sub") else mins)
                        if p.get("sub") and mins >= 1 and on + mins >= 89:
                            off = 999.0
                        gc = float(sum(1 for t, sc in timeline if sc != side_i and on < t <= off))
                    else:
                        gc = conceded_side[side_i] * min(mins, 90.0) / 90.0
                    tk, it_, cl, bl, rcv = (_f(s.get("totalTackle")), _f(s.get("interceptionWon")), _f(s.get("totalClearance")),
                                            _f(s.get("outfielderBlock")), _f(s.get("ballRecovery")))
                    self._F.extend((
                        _f(s.get("goals")), _f(s.get("goalAssist")), xg, _f(s.get("expectedAssists")), _f(s.get("saves")),
                        _f(s.get("ownGoals")), _f(s.get("penaltyMiss")), float(yc), float(rc),
                        tk + it_ + cl + bl, tk + it_ + cl + bl + rcv, gc,
                    ))
                    n_rows += 1
            if not n_rows:
                continue
            self._seen.add(str(gid))
            self._m["gid"].append(int(gid) if str(gid).isdigit() else -1)
            self._m["day"].append(day)
            self._m["comp"].append(ci)
            self._m["th"].append(int(m["home_id"]) if m.get("home_id") is not None else -1)
            self._m["ta"].append(int(m["away_id"]) if m.get("away_id") is not None else -1)
            self._m["gh"].append(int(m["hs"]))
            self._m["ga"].append(int(m["as"]))
            self._mx.extend(npxg_side)
            added += 1
        return added

    def finish(self) -> Rows:
        I = {k: np.frombuffer(v, dtype=np.int64).copy() if len(v) else np.zeros(0, dtype=np.int64) for k, v in self._ints.items()}
        M = {k: np.frombuffer(v, dtype=np.int64).copy() if len(v) else np.zeros(0, dtype=np.int64) for k, v in self._m.items()}
        X = np.frombuffer(self._X, dtype=np.float32).astype(np.float64).reshape(-1, NF) if len(self._X) else np.zeros((0, NF))
        mx = np.frombuffer(self._mx, dtype=np.float32).astype(np.float64).reshape(-1, 2) if len(self._mx) else np.zeros((0, 2))
        return Rows(
            pid=I["pid"], match=I["match"], side=I["side"], day=I["day"], comp=I["comp"], sid=I["sid"], tid=I["tid"],
            start=I["start"], mins=np.frombuffer(self._mins, dtype=np.float32).astype(np.float64) if len(self._mins) else np.zeros(0),
            letter=I["letter"], role=I["role"],
            rating=np.frombuffer(self._rating, dtype=np.float32).astype(np.float64) if len(self._rating) else np.zeros(0),
            X=X, comps=list(self.comps), comp_scope=list(self.comp_scope), sids=list(self.sids), current=dict(self.current),
            m_day=M["day"], m_comp=M["comp"], m_tid=np.stack([M["th"], M["ta"]], axis=1) if M["th"].size else np.zeros((0, 2), dtype=np.int64),
            m_npxg=mx, m_goals=np.stack([M["gh"], M["ga"]], axis=1) if M["gh"].size else np.zeros((0, 2), dtype=np.int64),
            m_gid=M["gid"],
            F=np.frombuffer(self._F, dtype=np.float32).astype(np.float64).reshape(-1, NFF) if len(self._F) else np.zeros((0, NFF)),
        )


# ── prior rates and the match design ─────────────────────────────────────────

def _club_rows(R: Rows) -> np.ndarray:
    club = np.array([s == "club" for s in R.comp_scope] + [False])
    return club[R.comp] if len(R) else np.zeros(0, dtype=bool)


def position_means(R: Rows, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-90 mean of every feature and the mean rating, by Sofascore letter (row 4: everyone)."""
    mu = np.zeros((5, NF))
    mr = np.full(5, 6.7)
    for li in range(5):
        sel = mask & ((R.letter == li) if li < 4 else np.ones(len(R), dtype=bool))
        m90 = R.mins[sel].sum() / 90.0
        if m90 > 0:
            mu[li] = R.X[sel].sum(axis=0) / m90
        rated = sel & np.isfinite(R.rating)
        if R.mins[rated].sum() > 0:
            mr[li] = float(np.average(R.rating[rated], weights=R.mins[rated]))
    return mu, mr


def prior_rates(R: Rows, mask: np.ndarray, m0: float = PRIOR_MINUTES / 90.0) -> tuple[np.ndarray, np.ndarray]:
    """
    Each line's prior per-90 rates and prior rating: the player's matches on
    earlier days only (every competition in `mask`), shrunk by `m0` matches' worth
    of minutes toward his letter's mean, itself measured on earlier days only
    (until a letter has 900 minutes, the mean over every letter; on the first day
    nobody has a history: zero rates and a 6.7 rating for everyone).
    """
    n = len(R)
    out = np.zeros((n, NF))
    out_r = np.zeros(n)
    if not n:
        return out, out_r
    pids, pix = np.unique(R.pid, return_inverse=True)
    acc = np.zeros((pids.size, NF))
    accm = np.zeros(pids.size)
    acc_rw = np.zeros(pids.size)
    acc_rm = np.zeros(pids.size)
    lix = np.where(R.letter >= 0, R.letter, 4)
    # Expanding position means: rows 0-3 the letters, row 4 everyone.
    pos_x = np.zeros((5, NF))
    pos_m = np.zeros(5)
    pos_rw = np.zeros(5)
    pos_rm = np.zeros(5)
    order = np.argsort(R.day, kind="stable")
    days = R.day[order]
    bounds = np.flatnonzero(np.diff(days)) + 1
    first = True
    for block in np.split(order, bounds):
        if first:
            mu, mr = np.zeros((5, NF)), np.full(5, 6.7)
            first = False
        else:
            mu = np.where((pos_m >= 900.0)[:, None], pos_x / np.maximum(pos_m, 1.0)[:, None] * 90.0, (pos_x[4] / max(pos_m[4], 1.0) * 90.0)[None, :])
            mr = np.where(pos_rm >= 900.0, pos_rw / np.maximum(pos_rm, 1.0), pos_rw[4] / max(pos_rm[4], 1.0) if pos_rm[4] > 0 else 6.7)
        p = pix[block]
        m90 = accm[p] / 90.0
        out[block] = (acc[p] + m0 * mu[lix[block]]) / (m90 + m0)[:, None]
        out_r[block] = (acc_rw[p] + m0 * 90.0 * mr[lix[block]]) / (acc_rm[p] + m0 * 90.0)
        use = block[mask[block]]
        if use.size:
            np.add.at(acc, pix[use], R.X[use])
            np.add.at(accm, pix[use], R.mins[use])
            rated = use[np.isfinite(R.rating[use])]
            np.add.at(acc_rw, pix[rated], R.rating[rated] * R.mins[rated])
            np.add.at(acc_rm, pix[rated], R.mins[rated])
            for li in (lix[use], np.full(use.size, 4)):
                np.add.at(pos_x, li, R.X[use])
                np.add.at(pos_m, li, R.mins[use])
            for li in (lix[rated], np.full(rated.size, 4)):
                np.add.at(pos_rw, li, R.rating[rated] * R.mins[rated])
                np.add.at(pos_rm, li, R.mins[rated])
    return out, out_r


@dataclass

class Design:
    """One row per club match with both line-ups: home minus away aggregates and the outcomes."""

    match: np.ndarray        # match index
    day: np.ndarray
    dA: np.ndarray           # (n, NF) minutes-weighted prior rates, home - away
    dR: np.ndarray           # minutes-weighted prior rating, home - away
    dT: np.ndarray           # team prior xG difference per match, home - away
    y_xgd: np.ndarray        # non-penalty xG difference
    y_gd: np.ndarray         # goal difference


def match_design(R: Rows, mask: np.ndarray, k0: float = 3.0) -> Design:
    prior, prior_r = prior_rates(R, mask)
    n_m = R.m_day.size
    A = np.zeros((n_m * 2, NF))
    Rt = np.zeros(n_m * 2)
    M = np.zeros(n_m * 2)
    cnt = np.zeros(n_m * 2)
    key = R.match * 2 + R.side
    w = R.mins / 90.0
    np.add.at(A, key, prior * w[:, None])
    np.add.at(Rt, key, prior_r * w)
    np.add.at(M, key, R.mins)
    np.add.at(cnt, key, 1)
    club_m = np.array([s == "club" for s in R.comp_scope] + [False])[R.m_comp] if n_m else np.zeros(0, dtype=bool)
    ok = club_m & (M[0::2] >= 900) & (M[1::2] >= 900) & (cnt[0::2] >= 10) & (cnt[1::2] >= 10)
    # Each team's prior non-penalty xG difference per match, from its earlier matches.
    T = np.zeros(n_m * 2)
    order = np.argsort(R.m_day, kind="stable")
    acc: dict[int, list[float]] = {}
    days = R.m_day[order]
    bounds = np.flatnonzero(np.diff(days)) + 1 if order.size else np.zeros(0, dtype=int)
    for block in (np.split(order, bounds) if order.size else []):
        for mi in block:
            for s in (0, 1):
                t = int(R.m_tid[mi, s])
                a = acc.get(t)
                T[mi * 2 + s] = (a[0] / (a[1] + k0)) if a else 0.0
        for mi in block:
            if not club_m[mi]:
                continue
            xgd = R.m_npxg[mi, 0] - R.m_npxg[mi, 1]
            for s, sign in ((0, 1.0), (1, -1.0)):
                t = int(R.m_tid[mi, s])
                a = acc.setdefault(t, [0.0, 0.0])
                a[0] += sign * xgd
                a[1] += 1.0
    idx = np.flatnonzero(ok)
    return Design(
        match=idx, day=R.m_day[idx], dA=A[idx * 2] - A[idx * 2 + 1], dR=Rt[idx * 2] - Rt[idx * 2 + 1],
        dT=T[idx * 2] - T[idx * 2 + 1], y_xgd=R.m_npxg[idx, 0] - R.m_npxg[idx, 1],
        y_gd=(R.m_goals[idx, 0] - R.m_goals[idx, 1]).astype(np.float64),
    )


# ── fitting ──────────────────────────────────────────────────────────────────

def fit_weights(Z: np.ndarray, y: np.ndarray, lam: float) -> tuple[np.ndarray, float]:
    """Ridge with non-negative weights: y ≈ h + Z·beta, beta >= 0; Z on its own scale, ridge on standardised columns."""
    from scipy.optimize import lsq_linear

    sd = Z.std(axis=0)
    sd[sd <= 1e-12] = 1.0
    Zs = Z / sd
    n, k = Zs.shape
    A = np.vstack([np.hstack([Zs, np.ones((n, 1))]), np.hstack([math.sqrt(lam) * np.eye(k), np.zeros((k, 1))])])
    b = np.concatenate([y, np.zeros(k)])
    lb = np.concatenate([np.zeros(k), [-np.inf]])
    ub = np.full(k + 1, np.inf)
    res = lsq_linear(A, b, bounds=(lb, ub), method="bvls" if k < 40 else "trf")
    return res.x[:k] / sd, float(res.x[k])


LAMBDAS = (1.0, 10.0, 100.0, 1000.0)


def fit_weights_cv(Z: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, float]:
    """The ridge chosen on the last 20% of the (time-ordered) training rows, then refitted on all of them."""
    n = len(y)
    cut = int(n * 0.8)
    best, best_lam = None, LAMBDAS[1]
    if cut >= 50 and n - cut >= 20:
        for lam in LAMBDAS:
            beta, h = fit_weights(Z[:cut], y[:cut], lam)
            sse = float(((y[cut:] - h - Z[cut:] @ beta) ** 2).sum())
            if best is None or sse < best:
                best, best_lam = sse, lam
    beta, h = fit_weights(Z, y, best_lam)
    return beta, h, best_lam


def _ols(cols: list[np.ndarray], y: np.ndarray) -> np.ndarray:
    A = np.column_stack([np.ones_like(y)] + cols)
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    return coef


def _ols_pred(coef: np.ndarray, cols: list[np.ndarray], n: int) -> np.ndarray:
    return np.column_stack([np.ones(n)] + cols) @ coef


def stack_weights(v: np.ndarray, r: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Second stage: y ≈ c + a·(box-score index) + b·(prior rating), a and b non-negative."""
    coef = _ols([v, r], y)
    a, b = float(coef[1]), float(coef[2])
    if b < 0:
        a, b = float(_ols([v], y)[1]), 0.0
    if a < 0:
        a, b = 0.0, max(float(_ols([r], y)[1]), 0.0)
    return a, b


def validate(D: Design, folds: int = 5, burn: float = 0.4) -> dict:
    """
    Walk-forward comparison on matches the models have not seen. Matches are in
    date order; the last (1 - burn) are cut into `folds` blocks and each block is
    predicted by models fitted on every earlier match. Every predictor uses only
    information from before the match day (prior rates, prior ratings, prior team
    xG difference). Reports out-of-sample R^2 against a home-advantage-only model.
    """
    n = D.match.size
    order = np.argsort(D.day, kind="stable")
    if n < 200:
        return {"ok": False, "reason": f"only {n} club matches with both line-ups", "n_matches": int(n)}
    start = int(n * burn)
    edges = np.linspace(start, n, folds + 1).astype(int)
    names = ("home", "rating", "team", "box", "value")
    sse = {t: {k: 0.0 for k in names} for t in ("xgd", "gd")}
    n_test = 0
    lams = []
    for f in range(folds):
        tr, te = order[: edges[f]], order[edges[f]: edges[f + 1]]
        # A block that shares a day with the training data would leak: start each block on a new day.
        te = te[D.day[te] > D.day[tr].max()] if tr.size else te
        if te.size < 20:
            continue
        beta, h, lam = fit_weights_cv(D.dA[tr], D.y_xgd[tr])
        lams.append(lam)
        v_tr, v_te = D.dA[tr] @ beta, D.dA[te] @ beta
        n_test += te.size
        for tgt, y in (("xgd", D.y_xgd), ("gd", D.y_gd)):
            ytr, yte = y[tr], y[te]
            # "value" is the published model: the box-score index and the prior rating, stacked on the
            # training matches; "box" is the box-score index alone.
            a, b = stack_weights(v_tr, D.dR[tr], D.y_xgd[tr])
            s_tr, s_te = a * v_tr + b * D.dR[tr], a * v_te + b * D.dR[te]
            preds = {
                "home": np.full(te.size, ytr.mean()),
                "rating": _ols_pred(_ols([D.dR[tr]], ytr), [D.dR[te]], te.size),
                "team": _ols_pred(_ols([D.dT[tr]], ytr), [D.dT[te]], te.size),
                "box": _ols_pred(_ols([v_tr], ytr), [v_te], te.size),
                "value": _ols_pred(_ols([s_tr], ytr), [s_te], te.size),
            }
            for k, p in preds.items():
                sse[tgt][k] += float(((yte - p) ** 2).sum())
    if not n_test:
        return {"ok": False, "reason": "no test block", "n_matches": int(n)}
    out = {"ok": True, "n_matches": int(n), "n_test": int(n_test), "folds": folds, "burn_in": burn,
           "first_test_day": date.fromordinal(int(D.day[order[start]])).isoformat(),
           "lambdas": sorted(set(lams)), "r2": {}}
    for tgt in ("xgd", "gd"):
        base = sse[tgt]["home"]
        out["r2"][tgt] = {k: round(1.0 - sse[tgt][k] / base, 4) for k in names if k != "home"}
        out["r2"][tgt]["rmse_home"] = round(math.sqrt(base / n_test), 4)
    return out


# ── the whole model ──────────────────────────────────────────────────────────

@dataclass
class ValueModel:
    """Fitted weights, validation and the per-competition centring and offsets."""

    beta: np.ndarray                    # box-score weights (goals of xG difference per action), sign-applied
    scale: float                        # second stage: weight of the box-score index
    rating_w: float                     # second stage: goals per 90 per rating point
    lam: float
    fitted: bool
    n_fit: int
    validation: dict
    centre: dict[str, float] = field(default_factory=dict)   # comp -> mean gross goals added per 90
    offset: dict[str, float] = field(default_factory=dict)   # comp -> strength v the pool average (goals per match)
    reliability: dict = field(default_factory=dict)

    def weights(self) -> list[dict]:
        out = [{"key": k, "label": lbl, "component": comp, "sign": sign, "padj": padj,
                "weight": round(float(self.beta[i]) * sign * self.scale, 5)} for i, (k, lbl, comp, sign, padj, _) in enumerate(FEATURES)]
        out.append({"key": "rating", "label": "Sofascore match rating (per point above 6.0)", "component": "Rating", "sign": 1,
                    "padj": False, "weight": round(self.rating_w, 5)})
        return out


def default_beta() -> np.ndarray:
    return np.array([DEFAULT_BETA[k] for k in FKEYS], dtype=np.float64)


def rating_input(R: Rows) -> np.ndarray:
    """Per line: (rating - 6.0) x minutes / 90; a line without a rating counts at 6.5 (a typical short cameo)."""
    rt = np.where(np.isfinite(R.rating), R.rating, 6.5)
    return (rt - RATING_BASE) * R.mins / 90.0


def gross_values(R: Rows, vm: "ValueModel") -> np.ndarray:
    """Per line, before centring: (n, len(COMPONENTS) + 1) goals by box-score component, then the rating part."""
    out = np.zeros((len(R), len(COMPONENTS) + 1))
    if not len(R):
        return out
    contrib = R.X * (vm.beta * vm.scale)[None, :]
    for j in range(NF):
        out[:, COMP_OF[j]] += contrib[:, j]
    out[:, -1] = vm.rating_w * rating_input(R)
    return out


def fit_model(R: Rows, offsets: dict[str, float] | None = None, do_validate: bool = True) -> ValueModel:
    club = _club_rows(R)
    D = match_design(R, club)
    n = D.match.size
    validation = validate(D) if do_validate else {"ok": False, "reason": "skipped"}
    if n >= MIN_FIT_MATCHES:
        order = np.argsort(D.day, kind="stable")
        beta, _h, lam = fit_weights_cv(D.dA[order], D.y_xgd[order])
        scale, rating_w = stack_weights(D.dA @ beta, D.dR, D.y_xgd)
        fitted = True
    else:
        beta, lam, fitted = default_beta(), float("nan"), False
        scale, rating_w = 1.0, DEFAULT_RATING_W
    vm = ValueModel(beta=beta, scale=scale, rating_w=rating_w, lam=lam, fitted=fitted, n_fit=int(n), validation=validation,
                    offset=dict(offsets or {}))
    # Centre every competition on its own mean gross goals added per 90.
    gross = gross_values(R, vm).sum(axis=1)
    for ci, slug in enumerate(R.comps):
        sel = R.comp == ci
        m90 = R.mins[sel].sum() / 90.0
        vm.centre[slug] = float(gross[sel].sum() / m90) if m90 > 0 else 0.0
    vm.reliability = split_half(R, vm)
    return vm


def row_shift(R: Rows, vm: ValueModel) -> np.ndarray:
    """Per line: (minutes / 90) x (the competition's strength / 11 - its centre)."""
    adj = np.array([vm.offset.get(s, 0.0) / 11.0 - vm.centre.get(s, 0.0) for s in R.comps] + [0.0])
    return (R.mins / 90.0) * adj[R.comp] if len(R) else np.zeros(0)


def row_values(R: Rows, vm: ValueModel) -> np.ndarray:
    """Per line: (n, len(COMPONENTS_OUT)) goals added by component, the last column the competition shift."""
    g = gross_values(R, vm)
    return np.hstack([g, row_shift(R, vm)[:, None]]) if len(R) else np.zeros((0, len(COMPONENTS_OUT)))


def split_half(R: Rows, vm: ValueModel, min_minutes: float = 1800.0) -> dict:
    """Odd against even appearances: how repeatable value per 90, its box-score part and rating are (club matches)."""
    club = _club_rows(R)
    if not club.any():
        return {}
    vals = row_values(R, vm)
    v = vals.sum(axis=1)
    box = vals[:, :len(COMPONENTS)].sum(axis=1)
    rows = np.flatnonzero(club)
    order = rows[np.lexsort((R.match[rows], R.day[rows], R.pid[rows]))]
    pid = R.pid[order]
    starts = np.r_[0, np.flatnonzero(np.diff(pid)) + 1]
    rank = np.arange(order.size) - np.repeat(starts, np.diff(np.r_[starts, order.size]))
    half = rank % 2
    acc: dict[int, list[float]] = {}
    for i, r in enumerate(order):
        a = acc.setdefault(int(R.pid[r]), [0.0] * 10)
        h = int(half[i]) * 5
        m = float(R.mins[r])
        a[h] += float(v[r])
        a[h + 1] += float(box[r])
        a[h + 2] += m
        if np.isfinite(R.rating[r]):
            a[h + 3] += float(R.rating[r]) * m
            a[h + 4] += m
    va, vb, ba, bb, ra, rb = [], [], [], [], [], []
    for a in acc.values():
        if a[2] >= min_minutes / 2 and a[7] >= min_minutes / 2 and a[4] > 0 and a[9] > 0:
            va.append(a[0] / a[2] * 90)
            vb.append(a[5] / a[7] * 90)
            ba.append(a[1] / a[2] * 90)
            bb.append(a[6] / a[7] * 90)
            ra.append(a[3] / a[4])
            rb.append(a[8] / a[9])
    if len(va) < 30:
        return {"n_players": len(va)}

    def corr(x, y) -> float:
        return round(float(np.corrcoef(x, y)[0, 1]), 3)

    return {"n_players": len(va), "min_minutes": min_minutes, "value_r": corr(va, vb), "box_r": corr(ba, bb), "rating_r": corr(ra, rb)}


# ── season lines ─────────────────────────────────────────────────────────────

def xpts_slope(mu: float, max_goals: int = 10) -> float:
    """Expected points gained per goal of expected goal difference per match, two Poisson sides at rate mu."""
    def xpts(lf: float, la: float) -> float:
        k = np.arange(max_goals + 1)
        fact = np.array([math.factorial(int(i)) for i in k], dtype=np.float64)
        pf = np.exp(-lf) * lf ** k / fact
        pa = np.exp(-la) * la ** k / fact
        m = np.outer(pf, pa)
        return 3.0 * float(np.tril(m, -1).sum()) + float(np.trace(m))
    mu = max(float(mu or 1.35), 0.3)
    h = 0.05
    # From (mu - h/2, mu + h/2) to (mu + h/2, mu - h/2) the expected goal difference moves by 2h.
    return (xpts(mu + h / 2, mu - h / 2) - xpts(mu - h / 2, mu + h / 2)) / (2 * h)


def percentile_rank(values: np.ndarray, x: float) -> int:
    if values.size == 0:
        return 50
    below = float((values < x).sum())
    ties = float((values == x).sum())
    return int(round(100.0 * (below + 0.5 * ties) / values.size))


@dataclass
class Line:
    """Aggregated value of one group of player-match lines."""

    mins: float = 0.0
    apps: int = 0
    starts: int = 0
    comp: np.ndarray = field(default_factory=lambda: np.zeros(len(COMPONENTS_OUT)))
    role_min: dict[int, float] = field(default_factory=dict)
    rt_w: float = 0.0
    rt_m: float = 0.0
    last_day: int = 0
    tid: int = -1
    by_comp: dict[int, float] = field(default_factory=dict)
    letters: dict[int, float] = field(default_factory=dict)

    @property
    def v(self) -> float:
        return float(self.comp.sum())

    @property
    def rate(self) -> float:
        return self.v / (self.mins / 90.0) if self.mins > 0 else 0.0

    def comp_rate(self) -> np.ndarray:
        return self.comp / (self.mins / 90.0) if self.mins > 0 else np.zeros(len(COMPONENTS_OUT))

    @property
    def rating(self) -> float | None:
        return self.rt_w / self.rt_m if self.rt_m > 0 else None

    def letter(self) -> str | None:
        return LETTERS[max(self.letters.items(), key=lambda kv: kv[1])[0]] if self.letters else None


def aggregate_lines(R: Rows, vals: np.ndarray, rows: np.ndarray, key_of: Callable[[int], Any]) -> dict[Any, Line]:
    """Sum the per-line values `vals` of `rows` into lines keyed by key_of(row) (None skips)."""
    out: dict[Any, Line] = {}
    for r in rows:
        r = int(r)
        key = key_of(r)
        if key is None:
            continue
        ln = out.get(key)
        if ln is None:
            ln = out[key] = Line()
        mins = float(R.mins[r])
        ln.mins += mins
        ln.apps += 1
        ln.starts += int(R.start[r])
        ln.comp += vals[r]
        if R.role[r] >= 0:
            ln.role_min[int(R.role[r])] = ln.role_min.get(int(R.role[r]), 0.0) + mins
        if R.letter[r] >= 0:
            ln.letters[int(R.letter[r])] = ln.letters.get(int(R.letter[r]), 0.0) + mins
        if np.isfinite(R.rating[r]):
            ln.rt_w += float(R.rating[r]) * mins
            ln.rt_m += mins
        if int(R.day[r]) >= ln.last_day:
            ln.last_day = int(R.day[r])
            ln.tid = int(R.tid[r])
        ln.by_comp[int(R.comp[r])] = ln.by_comp.get(int(R.comp[r]), 0.0) + mins
    return out


def modal_role(role_min: dict[int, float], letter: str | None) -> str:
    """The role a player starts in most (by minutes), else his letter's coarse role."""
    if role_min:
        return ROLES[max(role_min.items(), key=lambda kv: kv[1])[0]]
    return LETTER_ROLE.get(letter or "", "MF")


def unit_of_role(role: str) -> str:
    return UNIT_OF.get(role) or COARSE_UNIT.get(role, "MID")


def roles_of_unit(unit: str) -> tuple[str, ...]:
    for u, _, rs in UNITS:
        if u == unit:
            return rs
    return ()

# ── ageing ───────────────────────────────────────────────────────────────────

def ageing_curve(pairs: list[tuple[float, float, float]], lo: int = 17, hi: int = 38) -> dict[int, float]:
    """
    Delta method: `pairs` are (age, change in rating to the next season, weight).
    A weighted quadratic in age smooths the yearly changes; returns age -> change.
    """
    if len(pairs) < 50:
        # Too little data: a generic curve (gains to 25, flat to 29, declines after).
        return {a: (0.06 if a < 22 else 0.03 if a < 25 else 0.0 if a < 29 else -0.04 if a < 32 else -0.08) for a in range(lo, hi + 1)}
    a = np.array([p[0] for p in pairs], dtype=np.float64)
    d = np.array([p[1] for p in pairs], dtype=np.float64)
    w = np.array([p[2] for p in pairs], dtype=np.float64)
    keep = (a >= lo) & (a <= hi) & np.isfinite(d)
    a, d, w = a[keep], d[keep], w[keep]
    A = np.column_stack([np.ones_like(a), a - 27.0, (a - 27.0) ** 2])
    sw = np.sqrt(w)
    coef, *_ = np.linalg.lstsq(A * sw[:, None], d * sw, rcond=None)
    return {age: round(float(coef[0] + coef[1] * (age - 27.0) + coef[2] * (age - 27.0) ** 2), 4) for age in range(lo, hi + 1)}


def continuation_curve(ages: list[float], lo: int = 17, hi: int = 40, flat_until: int = 26) -> dict[int, float]:
    """
    The chance a regular of each age is still a regular a year later, from the age
    profile of this year's regulars: with birth cohorts of similar size, the ratio
    n(age + 1) / n(age) traces how careers thin out. 1 up to `flat_until`, then a
    three-year centred average, never above 1 and never rising with age.
    """
    cnt: dict[int, int] = {}
    for a in ages:
        if a is not None and lo <= int(a) <= hi + 1:
            cnt[int(a)] = cnt.get(int(a), 0) + 1
    raw: dict[int, float] = {}
    for a in range(lo, hi + 1):
        n0, n1 = cnt.get(a, 0), cnt.get(a + 1, 0)
        raw[a] = min(1.0, n1 / n0) if n0 >= 5 else (0.0 if a >= 35 else 1.0)
    out: dict[int, float] = {}
    prev = 1.0
    for a in range(lo, hi + 1):
        if a <= flat_until:
            v = 1.0
        else:
            win = [raw[x] for x in (a - 1, a, a + 1) if lo <= x <= hi]
            v = min(prev, sum(win) / len(win))
        out[a] = round(max(v, 0.0), 4)
        prev = out[a]
    return out


# ── windows ──────────────────────────────────────────────────────────────────

def window_status(slug: str, today: date) -> dict | None:
    spans = WINDOWS.get(slug)
    if not spans:
        return None

    def contains(span, d: date) -> bool:
        (m1, d1), (m2, d2) = span
        a, b, x = (m1, d1), (m2, d2), (d.month, d.day)
        return a <= x <= b if a <= b else (x >= a or x <= b)

    for span in spans:
        if contains(span, today):
            (m2, d2) = span[1]
            return {"open": True, "until": f"{d2} {MONTHS[m2 - 1]}", "spans": [[list(s[0]), list(s[1])] for s in spans]}
    nxt = None
    for k in range(1, 370):
        d = today + timedelta(days=k)
        if any(contains(s, d) for s in spans):
            nxt = d
            break
    return {"open": False, "next": f"{nxt.day} {MONTHS[nxt.month - 1]} {nxt.year}" if nxt else None,
            "spans": [[list(s[0]), list(s[1])] for s in spans]}
