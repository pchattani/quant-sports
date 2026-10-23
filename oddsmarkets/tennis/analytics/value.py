"""
The Value section (data/<T>/value.json and data/<T>/value_validation.json): who is likely to rise or fall over the
next 6-12 months, how much of a record is luck, and where the ranking and the market disagree with the model.

Everything here is computed from the stores, the Elo / game-share Elo histories, the serve/return fits, the committed
blend weights and (for the market view) the closing odds and the Kalshi research cache. Nothing is fitted on the
outcomes of the matches it describes except where stated (the luck expectations of a season use that season's
serve/return fit, as the catalogue's clutch metrics do).

1. The match table (`match_table`)
   One row per player per finished match of any level (walkovers included): date, level, round, best of, status,
   games won and lost, the ranks and points on the row, the pre-match Elo of both players (surface-blended, the Elo
   probability of the row's player), the de-vigged closing price (Pinnacle, else Betfair, else the average), and for
   WTA matches with statistics the points won and the break points. Each tour-level main-draw row also carries the
   player's seed band in the event (the order of the entrants' ranks: 1-2, 3-4, 5-8, 9-16, 17-32, unseeded).

2. Model rating
   The match price is logit p = w_elo logit(Elo p) + w_sr logit(serve/return p) + w_gelo (game-share difference)
   (models/predict.py). Linearised around an even match on a neutral best-of-three hard court it is a difference of
   one number per player, on the Elo scale:

       R = w_elo E + (400 / ln 10) (w_sr beta (s + r) + w_gelo G)

   E = overall Elo, G = overall game-share Elo, s + r = serve plus return rating (the player's own surface mix),
   beta = d logit(chain P) / d(s + r) at an even match (computed from the chain, about 2 a unit). The displayed
   rating adds a constant so the active top 100 average the same as on Elo. Surface ratings use the surface-blended
   Elo and game-share Elo and the surface serve/return record. The "model rank" is the order of R among active
   players; the "rank the model implies" maps that order onto the official ranks held by the same set of players.

3. Breakout model
   Quarterly snapshots (1 January, April, July, October) from 2008 (ATP) / 2009 (WTA). Universe: players whose
   latest official rank on a match row in the 120 days before the snapshot is 150 or better. Target: the change in
   log rank to the rank observed nearest the snapshot + 12 months (or + 6 months), within 45 days; players with no
   rank observation there are "unobserved" (most dropped out of tour-level main draws). Features, all from data before
   the snapshot (FEATURES below). Ridge regression on standardised features, refitted every year on the snapshots
   whose target window had closed before 1 January of that year (walk-forward, no look-ahead), lambda and the
   shrinkage constant chosen on the dev years 2010-2017 only; 2018-2025 are reported as the test years. Breakout and
   regression probabilities are logistic fits of "rank improves by a third or more (and 5+ places)" and "rank worsens
   by half or more and 5+ places (or the player is unobserved)" on the distance of the prediction from that threshold at
   the player's rank and the log rank, fitted the same way.

4. Luck
   Per player and window: close-match luck = wins - sum of P(win | share of games won in the match), with the
   Pythagorean P = s^k / (s^k + (1 - s)^k), k fitted per best-of on the dev years; for WTA matches with statistics the
   same from the share of points won, and the gap between the two (converting points into games: break points and game
   points; shown, but not counted as luck, because it persists); tiebreaks and deciding sets against the chain's
   expectation (the catalogue's clutch measures); break
   points saved and converted against the player's own non-break-point serve and return rates in the match (plus the
   tour's pressure offset); draw luck = sum of Elo P(win v the actual opponent) - the mean Elo P(win) v the typical
   opponents of that level, round and seed band, placed relative to the strength of the event's field (so the events a
   player chooses are not luck: that is the strength of schedule, reported apart); free wins = walkovers and
   retirements received, each worth 1 - P(win at the stoppage). Wins above expectation = close-match luck + draw luck +
   free wins. Evidence that it is luck: season-to-season correlations (players with 20+ matches in both) and
   next-season win % predicted from raw against luck-adjusted win %.

5. Over / undervalue
   Official rank against the rank the model implies; ranking points against the points held at that rank; surface
   ratings against the overall rating; the market (de-vigged closing prices, Kalshi quotes before the start) against
   the model's pre-match price over the last 52 weeks, with the scoreboard of who was right. The market beat the model
   in the edge study (docs/research/tennis_edge.md), so the gaps are disagreements, not value bets.
"""
from __future__ import annotations

import bisect
import hashlib
import logging
import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np

from oddsmarkets.tennis import analytics as an

logger = logging.getLogger(__name__)

VERSION = 1
K_ELO = 400.0 / math.log(10.0)
SNAP_MONTHS = (1, 4, 7, 10)
FIRST_SNAP = {"atp": 2008, "wta": 2009}
FIRST_PRED_YEAR = {"atp": 2010, "wta": 2011}
DEV_YEARS = (2010, 2017)
TEST_YEARS = (2018, 2025)
HORIZONS = {"12m": 365, "6m": 182}
UNIVERSE = 150
MAP_RANKS = 300            # the over/undervalue table maps the model's order onto the official ranks inside this
RANK_BEFORE = 120          # days: the snapshot rank is the latest observation within this many days before
RANK_AROUND = 45           # days: the target rank is the observation nearest the target date within this window
RISE = math.log(2.0 / 3.0)  # a breakout: the rank improves by a third or more ...
RISE_PLACES = 5             # ... and by at least 5 places
FALL = math.log(1.5)        # a regression: the rank worsens by half or more and RISE_PLACES places (or is unobserved)
TOP_N = 10                  # the list sizes scored per snapshot
SHRINK_K = (0.0, 5.0, 10.0, 20.0, 40.0)    # gap * n / (n + k), n = rated matches in the last 12 months
LAMBDAS = (1.0, 10.0, 100.0, 1000.0)
LEVEL_GROUPS = ("slam", "m1000", "500", "250")
BANDS = ("1-2", "3-4", "5-8", "9-16", "17-32", "unseeded")
MIN_LUCK = 10               # tour-level matches in a window for the luck table
MIN_EVIDENCE = 20           # matches in both seasons for the year-to-year correlations
N_BOOT = 400
STATUS_CODE = {"done": 0, "ret": 1, "def": 2, "wo": 3}

FEATURES = [
    # key, label, how it reads
    ("lr", "Log rank", "the ranking level itself (rankings far down the list move more)"),
    ("gap", "Ranking v model", "log official rank minus log of the rank the model implies, shrunk by matches played"),
    ("age", "Age", "age at the snapshot, centred at 25"),
    ("age2", "Age squared", "the curvature of the age curve"),
    ("age_na", "Age unknown", "1 when there is no date of birth"),
    ("d_elo", "Elo trend", "Elo change over the last 6 months, in 100s"),
    ("d_rank", "Rank trend", "log rank change over the last 6 months"),
    ("idle", "Days out", "log(1 + days since the last rated match)"),
    ("n12", "Activity", "log(1 + rated matches in the last 12 months)"),
    ("drop", "Points to defend", "tour-level points that drop within the horizon / official points"),
    ("tl", "Tour-level share", "tour-level points in the ranking / official points (low = built on Challengers / ITF)"),
    ("luck", "Close-match luck", "close-match luck per match over the last 12 months"),
    ("draw", "Draw luck", "draw luck per match over the last 12 months"),
    ("mk", "Market v Elo", "the closing market's rating of the player minus Elo's, last 12 months, in 100s of Elo points"),
]
FKEYS = [f[0] for f in FEATURES]
BASELINES = {"rank_only": ["lr"], "rank_model": ["lr", "gap"], "full": FKEYS}


# Glossary entries for every number the Value pages show (analytics/glossary.py publishes them; a test checks them).
_G = "Value: "
VALUE_GLOSSARY: list[dict] = [
    # breakout
    {"key": "v_pred_rank", "label": "Predicted rank (12 or 6 months)", "group": _G + "Breakout", "fmt": "int", "lower": True,
     "desc": "Official rank now x exp(predicted change in log rank) from the breakout model: a ridge regression of the change in log "
             "rank over the horizon on the features below, refitted every year on past snapshots only (walk-forward)."},
    {"key": "v_pred_change", "label": "Predicted change in log rank", "group": _G + "Breakout", "fmt": "3", "lower": True,
     "desc": "The model's prediction of log(rank later) - log(rank now): -0.69 halves the rank number (a rise), +0.41 multiplies it "
             "by 1.5 (a fall)."},
    {"key": "v_range", "label": "Likely range", "group": _G + "Breakout", "fmt": "int",
     "desc": "The 10th to 90th percentile of the predicted rank, from the model's past errors for players in the same rank band "
             "(1-20, 21-50, 51-100, 101-150)."},
    {"key": "v_p_rise", "label": "Breakout probability", "group": _G + "Breakout", "fmt": "prob",
     "desc": "P(the rank improves by a third or more and by at least 5 places over the horizon): a logistic fit on the prediction's "
             "distance from that threshold at the player's rank "
             "and the log rank, walk-forward. Not shown for the top 10."},
    {"key": "v_p_fall", "label": "Regression probability", "group": _G + "Breakout", "fmt": "prob", "lower": True,
     "desc": "P(the rank worsens by half or more and by at least 5 places, or the player has no tour-level main-draw rank on "
             "record at the horizon), fitted "
             "like the breakout probability."},
    {"key": "v_elo_change", "label": "Predicted Elo change", "group": _G + "Breakout", "fmt": "signed",
     "desc": "The same features fitted to the change in overall Elo over the horizon (inactivity pulls Elo towards 1500, so long "
             "absences show here too)."},
    {"key": "v_reasons", "label": "Reasons", "group": _G + "Breakout", "fmt": "3",
     "desc": "The largest feature contributions to the prediction against the average snapshot (coefficient x standardised value, "
             "in log-rank units, shown as a % change in rank): what moves this player's forecast."},
    {"key": "v_gap", "label": "Ranking v model", "group": _G + "Breakout", "fmt": "3",
     "desc": "log(official rank) - log(the rank the model implies). Positive: the ranking is worse than the model's rating "
             "(underrated by the ranking); negative: overrated."},
    {"key": "v_age_curve", "label": "Age curve", "group": _G + "Breakout", "fmt": "3",
     "desc": "The mean change in log rank over the next 12 months by age at the snapshot, all snapshots since 2008 / 2009 "
             "(dates of birth from the WTA API and ESPN)."},
    {"key": "v_d_elo", "label": "Elo trend", "group": _G + "Breakout", "fmt": "signed",
     "desc": "Overall Elo now minus six months ago."},
    {"key": "v_d_rank", "label": "Rank trend", "group": _G + "Breakout", "fmt": "3", "lower": True,
     "desc": "log(rank now) - log(the rank six months ago) where both are on record (negative = rising)."},
    {"key": "v_idle", "label": "Days out", "group": _G + "Breakout", "fmt": "int", "lower": True,
     "desc": "Days since the last rated match (tour level, qualifying, Challenger / WTA 125)."},
    {"key": "v_n12", "label": "Matches in 12 months", "group": _G + "Breakout", "fmt": "int",
     "desc": "Rated matches in the last 12 months (the sample behind the ratings)."},
    {"key": "v_drop", "label": "Points to defend", "group": _G + "Breakout", "fmt": "int", "lower": True,
     "desc": "Tour-level ranking points from the last 12 months that drop off within the horizon (Slams, Finals, 1000s, 500s, "
             "250s; Challenger / WTA 125 and ITF points are not in the data)."},
    {"key": "v_exp_earn", "label": "Expected points at this level", "group": _G + "Breakout", "fmt": "int",
     "desc": "The mean tour-level points earned over the horizon by players the model rated at the same implied rank, all "
             "past snapshots: set against the points to defend, the points calendar."},
    {"key": "v_tl_share", "label": "Tour-level share", "group": _G + "Breakout", "fmt": "pct",
     "desc": "Tour-level points in the ranking / official points: low means a ranking built mostly on Challengers or ITF events."},
    {"key": "v_mk_feature", "label": "Market v Elo", "group": _G + "Breakout", "fmt": "signed",
     "desc": "The rating of the player implied by the closing line (the market reference) minus Elo's over the last 12 months "
             "(Elo points, shrunk towards 0 by 10 matches): the breakout model's one market input."},
    # luck
    {"key": "v_close", "label": "Close-match luck", "group": _G + "Luck", "fmt": "signed",
     "desc": "Wins minus the sum over completed matches of P(win | share of games won): the Pythagorean expectation s^k / (s^k + "
             "(1 - s)^k), k fitted per best-of on matches to 2017 (about 20 for best of three). Winning the close ones beyond what "
             "the games deserve."},
    {"key": "v_pyth", "label": "Pythagorean expected wins", "group": _G + "Luck", "fmt": "1",
     "desc": "The sum of P(win | share of games won) over the completed matches (from the share of points won where WTA statistics "
             "exist: the points-based expectation)."},
    {"key": "v_tb_luck", "label": "Tiebreaks over expected", "group": _G + "Luck", "fmt": "signed",
     "desc": "Tiebreaks won minus the chain's P(win the tiebreak) from both players' serve and return strength."},
    {"key": "v_dec_luck", "label": "Deciding sets over expected", "group": _G + "Luck", "fmt": "signed",
     "desc": "Deciding sets won minus the chain's P(win the set) under the set's rule."},
    {"key": "v_conv", "label": "Points-to-games conversion", "group": _G + "Luck", "fmt": "signed", "scope": "wta_stats",
     "desc": "Expected wins from games minus expected wins from points (WTA matches with statistics): turning points into games. "
             "Shown, but not counted as luck: it persists from season to season."},
    {"key": "v_bp_saved", "label": "Break points saved over expected", "group": _G + "Luck", "fmt": "signed", "scope": "wta_stats",
     "desc": "Break points saved minus break points faced x (the player's serve points won outside break points + the tour's pressure offset)."},
    {"key": "v_bp_conv", "label": "Break points converted over expected", "group": _G + "Luck", "fmt": "signed", "scope": "wta_stats",
     "desc": "Break points converted minus chances x (the player's return points won outside break points + the tour's offset)."},
    {"key": "v_draw", "label": "Draw luck", "group": _G + "Luck", "fmt": "signed",
     "desc": "Sum of Elo P(win v the actual opponent) - the mean Elo P(win) v the typical opponents met at that level, round and "
             "seed band in earlier years, placed relative to the strength of the event's field."},
    {"key": "v_sos", "label": "Strength of schedule", "group": _G + "Luck", "fmt": "signed",
     "desc": "Mean opponent Elo minus the typical opponent's at the same level, round and seed band, relative to the other players "
             "in the window: the events chosen are included, so it is reported, not counted as luck."},
    {"key": "v_free", "label": "Free wins", "group": _G + "Luck", "fmt": "signed",
     "desc": "Walkovers and opponents' retirements received, each worth 1 - P(win at the stoppage) (Elo before the match, sets so "
             "far for a retirement)."},
    {"key": "v_total_luck", "label": "Wins above expectation", "group": _G + "Luck", "fmt": "signed",
     "desc": "Close-match luck + draw luck + free wins: the wins a record owes to luck. It regresses: its season-to-season "
             "correlation is close to zero (Validation view)."},
    {"key": "v_adj_win", "label": "Luck-adjusted win %", "group": _G + "Luck", "fmt": "pct",
     "desc": "(Wins - close-match luck - draw luck) / matches: predicts next season's win % better than the raw win %."},
    {"key": "v_yoy", "label": "Season-to-season correlation", "group": _G + "Luck", "fmt": "3",
     "desc": "Pearson correlation of a measure in one season with the same measure the next season (players with 20+ tour-level "
             "matches in both): near 0 for luck, high for skill."},
    # over / undervalue
    {"key": "v_model_rating", "label": "Model rating", "group": _G + "Over / undervalue", "fmt": "int",
     "desc": "The match forecast's blend linearised into one number per player on the Elo scale: w_elo x Elo + (400 / ln 10) x (w_sr x beta "
             "x (serve + return rating) + w_gelo x game-share Elo), offset so the active top 100 average as on Elo."},
    {"key": "v_model_rank", "label": "Model rank", "group": _G + "Over / undervalue", "fmt": "int", "lower": True,
     "desc": "Order of the model rating among players with a rated match in the last year and 10+ rated matches."},
    {"key": "v_implied_rank", "label": "Rank the model implies", "group": _G + "Over / undervalue", "fmt": "int", "lower": True,
     "desc": "The official rank held by the player in the same position of the official order: the k-th best model rating gets the "
             "k-th best official rank among the same players (those ranked inside the top 300)."},
    {"key": "v_pts_imp", "label": "Points at the implied rank", "group": _G + "Over / undervalue", "fmt": "int",
     "desc": "The official ranking points of the player who holds the implied rank: what the ranking would credit if it followed "
             "the model."},
    {"key": "v_surface", "label": "Surface rating", "group": _G + "Over / undervalue", "fmt": "int",
     "desc": "The model rating on one surface (surface-blended Elo and game-share Elo, the surface serve/return record), its rank, and "
             "the gap to the overall rating: a surface specialist's advantage."},
    # market
    {"key": "v_market_gap", "label": "Market v model", "group": _G + "Market", "fmt": "signed",
     "desc": "Mean over the player's matches of logit(market) - logit(model), in Elo points: positive = the market reference rates "
             "the player above the model. Market reference = the closing line with the margin removed (Pinnacle, else Betfair, else "
             "the average) or Kalshi's quote about 4 h before the start. A difference of opinion, not a signal: the market reference "
             "is the better forecaster."},
    {"key": "v_market_x", "label": "Expected wins: model, market", "group": _G + "Market", "fmt": "1",
     "desc": "Sums of the model's and the market's pre-match probabilities over the same matches, beside the actual wins."},
    {"key": "v_market_ll", "label": "Log-loss: model, market", "group": _G + "Market", "fmt": "3", "lower": True,
     "desc": "Mean -log P(actual result) of each forecaster on the same matches (lower is better)."},
    # validation
    {"key": "v_spearman", "label": "Rank correlation (Spearman)", "group": _G + "Validation", "fmt": "3",
     "desc": "Spearman correlation between the predicted and the actual change in log rank, players observed at the horizon; 95 % "
             "CI from 400 bootstrap resamples of players."},
    {"key": "v_hit_rate", "label": "Hit rate of the top 10", "group": _G + "Validation", "fmt": "pct",
     "desc": "Share of each snapshot's 10 most likely breakouts (outside the top 10, by breakout probability) that broke out, and "
             "of the 10 most likely regressions that regressed; the base rate is the share among all players."},
    {"key": "v_lift", "label": "Lift", "group": _G + "Validation", "fmt": "2",
     "desc": "Hit rate / base rate: 2.5 means the list finds breakouts 2.5 times as often as picking at random."},
    {"key": "v_recall", "label": "Recall", "group": _G + "Validation", "fmt": "pct",
     "desc": "Share of all breakouts at a snapshot that were in its top-10 list."},
    {"key": "v_brier", "label": "Brier score", "group": _G + "Validation", "fmt": "3", "lower": True,
     "desc": "Mean squared error of the breakout / regression probabilities, beside the base rate's."},
    {"key": "v_walk_forward", "label": "Walk-forward", "group": _G + "Validation", "fmt": "3",
     "desc": "Each year is predicted by a model fitted only on snapshots whose 12-month (6-month) outcome was known by 1 January of "
             "that year; settings chosen on 2010-2017, 2018-2025 reported as the test years."},
]
VALUE_MODEL_TERMS = [
    ("value_breakout", "Breakout model", "Value",
     "Quarterly snapshots of the official top 150 since 2008 (ATP) / 2009 (WTA): the change in log rank over 12 (and 6) months on the "
     "ranking v the model's rating, age, Elo and rank trends, days out, activity, points to defend, the tour-level share of the "
     "points, close-match and draw luck and the market's view; ridge regression refitted every year on past snapshots."),
    ("value_luck", "Luck decomposition", "Value",
     "A record split into what the performance deserved and what luck added: Pythagorean expectations from games (and points), "
     "the chain's tiebreak and deciding-set chances, break-point base rates, draws against the typical draw for the seed band, "
     "walkovers and retirements received."),
    ("value_rating", "Model rating", "Value",
     "One number per player from the match forecast's blend of Elo, serve/return and game-share Elo, on the Elo scale; the basis of "
     "the model rank and the over/undervalue table."),
]


# ---------------------------------------------------------------------------------------------- small maths

def _sig(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, float)))


def _logit(p, eps: float = 1e-4):
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    return np.log(p / (1 - p))


def elo_p(d: float, f: float = 1.0) -> float:
    return 1.0 / (1.0 + 10.0 ** (-f * d / 400.0))


def pyth(share, k):
    """Pythagorean expectation s^k / (s^k + (1 - s)^k) = sigmoid(k logit s)."""
    return _sig(k * _logit(share))


def fit_k(x: np.ndarray, y: np.ndarray, k0: float = 5.0) -> float:
    """MLE of k in P(y=1) = sigmoid(k x) (one parameter, no intercept) by Newton steps."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 10:
        return float("nan")
    k = k0
    for _ in range(50):
        p = _sig(k * x)
        g = float(np.sum((y - p) * x))
        h = float(np.sum(p * (1 - p) * x * x)) + 1e-9
        step = g / h
        k += step
        if abs(step) < 1e-8:
            break
    return float(k)


def rankdata(a: np.ndarray) -> np.ndarray:
    """Average ranks (1-based), ties shared."""
    from scipy.stats import rankdata as _rd
    return _rd(np.asarray(a, float))


def spearman(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 5:
        return float("nan")
    return pearson(rankdata(x[ok]), rankdata(y[ok]))


def pearson(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 3:
        return float("nan")
    xs, ys = x - x.mean(), y - y.mean()
    den = math.sqrt(float(xs @ xs) * float(ys @ ys))
    return float(xs @ ys) / den if den > 0 else float("nan")


def boot_ci(stat, groups: np.ndarray, *arrays, n: int = N_BOOT, seed: int = 0) -> tuple[float, float, float]:
    """(estimate, 2.5 %, 97.5 %) of stat(*arrays), resampling the clusters in `groups` (player ids) with
    replacement."""
    arrays = [np.asarray(a) for a in arrays]
    est = stat(*arrays)
    g = np.asarray(groups)
    uniq, inv = np.unique(g, return_inverse=True)
    if len(uniq) < 5:
        return est, float("nan"), float("nan")
    members = [np.nonzero(inv == k)[0] for k in range(len(uniq))]
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        pick = rng.integers(0, len(uniq), len(uniq))
        idx = np.concatenate([members[k] for k in pick])
        v = stat(*[a[idx] for a in arrays])
        if v == v:
            out.append(v)
    if len(out) < 20:
        return est, float("nan"), float("nan")
    lo, hi = np.percentile(out, [2.5, 97.5])
    return est, float(lo), float(hi)


def r3(x, nd: int = 3):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


# ---------------------------------------------------------------------------------------------- the match table

def _games(m: dict) -> tuple[int, int]:
    g1 = g2 = 0
    for s in m.get("sets") or []:
        try:
            g1 += int(s[0])
            g2 += int(s[1])
        except (TypeError, ValueError, IndexError):
            continue
    return g1, g2


def _sets_won(m: dict, rule: str) -> tuple[int, int]:
    """Completed sets won by p1 and p2 (a retirement's unfinished set is not counted)."""
    a = b = 0
    bo = 5 if int(m.get("best_of") or 3) == 5 else 3
    for k, s in enumerate(m.get("sets") or []):
        try:
            x, y = int(s[0]), int(s[1])
        except (TypeError, ValueError, IndexError):
            break
        hi, lo = max(x, y), min(x, y)
        decider = k == bo - 1
        done = (hi == 6 and lo <= 4) or (hi == 7 and lo in (5, 6)) or (decider and rule in ("adv", "tb12", "tb10") and hi >= 6
                                                                        and hi - lo >= 2)
        if not done:
            break
        if x > y:
            a += 1
        else:
            b += 1
    return a, b


def _book_p(odds: dict | None) -> tuple[float | None, str | None]:
    """De-vigged closing P(p1): Pinnacle, else the Betfair exchange, else the bookmakers' average."""
    for k in ("ps", "bfe", "avg"):
        p = an.devig2((odds or {}).get(k))
        if p is not None:
            return p, k
    return None, None


def _f(x) -> float:
    v = an.fnum(x)
    return float("nan") if v is None else v


def match_table(td: an.TourData) -> dict:
    """Column arrays, one row per player per finished match (any level; walkovers included), sorted by date.
    See the module docstring. Also {"by": {pid: row indices}}, "ranks": {pid: (days, ranks, points)}."""
    elo_w = float((td.elo_params() or {}).get("w_surf", 0.5))
    elo_f5 = float((td.elo_params() or {}).get("bo5", 1.0))
    ms = []
    for y in td.years:
        evs = td.events(y)
        for m in td.matches(y).values():
            if m.get("status") not in an.FINISHED or not m.get("winner") or not m.get("p1") or not m.get("p2"):
                continue
            if str(m["p1"]) == str(m["p2"]):
                continue
            d = an.day(m.get("date"))
            if d is None or abs(d.year - y) > 1:
                d = an.day((evs.get(m.get("event")) or {}).get("start"))
                if d is None:
                    continue
            ms.append((d.toordinal(), an.ROUND_ORDER.get(m.get("round"), 5), str(m.get("id")), m))
    ms.sort(key=lambda r: (r[0], r[1], r[2]))
    # seed bands: the order of each event's main-draw entrants by the rank they carried into their first match
    first_rank: dict[str, dict[str, int]] = defaultdict(dict)
    for d, ro, mid, m in ms:
        if not an.is_tour_level(m):
            continue
        ev = str(m.get("event"))
        for p, rk in ((m["p1"], m.get("rank1")), (m["p2"], m.get("rank2"))):
            if str(p) not in first_rank[ev]:
                first_rank[ev][str(p)] = an.inum(rk) or 100000
    first_elo: dict[str, dict[str, float]] = defaultdict(dict)
    for d, ro, mid, m in ms:
        if not an.is_tour_level(m) or m.get("status") == "wo":
            continue
        g = td.elo_row(str(m.get("id")))
        if g is None:
            continue
        ev = str(m.get("event"))
        for p, ai, si in ((str(g[2]), 8, 9), (str(g[3]), 10, 11)):
            if p not in first_elo[ev]:
                a_, s_ = an.fnum(g[ai]), an.fnum(g[si])
                if a_ is not None and s_ is not None:
                    first_elo[ev][p] = elo_w * s_ + (1 - elo_w) * a_
    field = {ev: float(np.mean(list(v.values()))) for ev, v in first_elo.items() if len(v) >= 8}
    band_of: dict[str, dict[str, int]] = {}
    for ev, ranks in first_rank.items():
        order = sorted(ranks, key=lambda p: (ranks[p], p))
        nseed = max(2, min(32, len(order) // 4))
        bands = {}
        for i, p in enumerate(order):
            pos = i + 1
            if pos > nseed or ranks[p] >= 100000:
                bands[p] = 5
            else:
                bands[p] = 0 if pos <= 2 else 1 if pos <= 4 else 2 if pos <= 8 else 3 if pos <= 16 else 4
        band_of[ev] = bands
    cols: dict[str, list] = {k: [] for k in (
        "d", "mid", "pid", "opp", "won", "st", "tl", "lvl", "rnd", "bo", "surf", "ev", "g", "gl", "sw", "sl",
        "rank", "orank", "pts", "em", "eo", "ep", "book", "bsrc", "tpw", "spw", "rpw", "bps", "bpf", "bpc", "bpo",
        "band", "rule", "side", "fe")}
    for d, ro, mid, m in ms:
        st = STATUS_CODE.get(m.get("status"), 0)
        tl = an.is_tour_level(m)
        lvl = str(m.get("level"))
        bo = 5 if int(m.get("best_of") or 3) == 5 else 3
        surf = str(m.get("surface") or "hard")
        surf = surf if surf in an.SURFACES else "hard"
        g1, g2 = _games(m)
        rule = an.chain_rule(m)
        s1, s2 = _sets_won(m, rule)
        bk, src = _book_p(m.get("odds"))
        g = td.elo_row(mid) if st != 3 else None
        em1 = em2 = ep1 = float("nan")
        if g is not None:
            a1, f1, a2, f2 = _f(g[8]), _f(g[9]), _f(g[10]), _f(g[11])
            em1, em2 = elo_w * f1 + (1 - elo_w) * a1, elo_w * f2 + (1 - elo_w) * a2
            ep1 = _f(g[12])
            if str(g[2]) != str(m["p1"]):            # defensive: rows follow the store's p1 / p2
                em1, em2, ep1 = em2, em1, 1 - ep1
        stt = m.get("stats") if isinstance(m.get("stats"), dict) else None
        sv = [None, None]
        if stt and isinstance(stt.get("p1"), dict) and isinstance(stt.get("p2"), dict):
            sv = [stt["p1"], stt["p2"]]
        winner = str(m["winner"])
        for side in (0, 1):
            me, op = (str(m["p1"]), str(m["p2"])) if side == 0 else (str(m["p2"]), str(m["p1"]))
            cols["d"].append(d)
            cols["side"].append(side)
            cols["mid"].append(mid)
            cols["pid"].append(me)
            cols["opp"].append(op)
            cols["won"].append(1 if winner == me else 0)
            cols["st"].append(st)
            cols["tl"].append(tl)
            cols["lvl"].append(lvl)
            cols["rnd"].append(str(m.get("round") or ""))
            cols["bo"].append(bo)
            cols["surf"].append(surf)
            cols["ev"].append(str(m.get("event")))
            cols["rule"].append(rule)
            cols["g"].append(g1 if side == 0 else g2)
            cols["gl"].append(g2 if side == 0 else g1)
            cols["sw"].append(s1 if side == 0 else s2)
            cols["sl"].append(s2 if side == 0 else s1)
            r_me, r_op = (m.get("rank1"), m.get("rank2")) if side == 0 else (m.get("rank2"), m.get("rank1"))
            cols["rank"].append(_f(r_me))
            cols["orank"].append(_f(r_op))
            cols["pts"].append(_f(m.get("pts1") if side == 0 else m.get("pts2")))
            cols["em"].append(em1 if side == 0 else em2)
            cols["eo"].append(em2 if side == 0 else em1)
            cols["ep"].append(ep1 if side == 0 else (1 - ep1 if ep1 == ep1 else ep1))
            cols["book"].append(bk if side == 0 else (1 - bk if bk is not None else None))
            cols["bsrc"].append(src)
            a, b = sv[side], sv[1 - side]
            tpw = spw = rpw = bps = bpf = bpc = bpo = float("nan")
            if a and b:
                ap, bp_ = _f(a.get("sv_pts")), _f(b.get("sv_pts"))
                aw = _f(a.get("fs_won")) + _f(a.get("ss_won"))
                bw = _f(b.get("fs_won")) + _f(b.get("ss_won"))
                if ap > 0 and bp_ > 0 and aw == aw and bw == bw:
                    tpw = (aw + bp_ - bw) / (ap + bp_)
                    bps, bpf = _f(a.get("bp_saved")), _f(a.get("bp_faced"))
                    bpc, bpo = _f(a.get("bp_conv")), _f(a.get("bp_opps"))
                    # serve / return points won outside break points (the BP-luck expectation's base rate)
                    if bpf == bpf and bps == bps and ap - bpf > 0:
                        spw = (aw - bps) / (ap - bpf)
                    if bpo == bpo and bpc == bpc and bp_ - bpo > 0:
                        rpw = (bp_ - bw - bpc) / (bp_ - bpo)
            for k, v in (("tpw", tpw), ("spw", spw), ("rpw", rpw), ("bps", bps), ("bpf", bpf), ("bpc", bpc), ("bpo", bpo)):
                cols[k].append(v)
            cols["band"].append((band_of.get(str(m.get("event"))) or {}).get(me, 5) if tl else -1)
            cols["fe"].append(field.get(str(m.get("event")), float("nan")) if tl else float("nan"))
    T: dict[str, Any] = {}
    for k, v in cols.items():
        if k in ("mid", "pid", "opp", "lvl", "rnd", "surf", "ev", "bsrc", "rule"):
            T[k] = np.array([x if x is not None else "" for x in v], dtype=object)
        elif k in ("won", "st", "bo", "g", "gl", "sw", "sl", "band", "d", "side"):
            T[k] = np.array(v, dtype=np.int64)
        elif k == "tl":
            T[k] = np.array(v, dtype=bool)
        else:
            T[k] = np.array([np.nan if x is None else x for x in v], dtype=float)
    n = len(T["d"])
    T["n"] = n
    T["f5"] = elo_f5
    by: dict[str, list] = defaultdict(list)
    for i, p in enumerate(T["pid"]):
        by[p].append(i)
    T["by"] = {p: np.array(ix, dtype=np.int64) for p, ix in by.items()}
    # walkovers carry no Elo row: Elo P from each player's latest overall rating before the day
    _fill_walkover_elo(td, T, elo_f5)
    return T


def _fill_walkover_elo(td: an.TourData, T: dict, f5: float) -> None:
    rows = td.elo.get("rows") or []
    init = td.elo.get("init") or {}
    series: dict[str, tuple[list, list]] = {}
    for g in rows:
        dd = an.day(g[1]).toordinal()
        for pid, ai in ((g[2], 13), (g[3], 15)):
            s = series.setdefault(str(pid), ([], []))
            s[0].append(dd)
            s[1].append(float(g[ai]))

    def rating(pid: str, d: int) -> float:
        s = series.get(pid)
        if not s:
            return float(init.get(pid, 1500.0))
        i = bisect.bisect_left(s[0], d) - 1
        return s[1][i] if i >= 0 else float(init.get(pid, 1500.0))
    for i in np.nonzero(T["st"] == 3)[0]:
        a, b = rating(T["pid"][i], int(T["d"][i])), rating(T["opp"][i], int(T["d"][i]))
        T["em"][i], T["eo"][i] = a, b
        T["ep"][i] = elo_p(a - b, f5 if T["bo"][i] == 5 else 1.0)


def rank_series(T: dict) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """{pid: (days, ranks, points)} of every rank observation on a match row, by date."""
    out = {}
    for p, ix in T["by"].items():
        r = T["rank"][ix]
        ok = np.isfinite(r) & (r > 0)
        if ok.any():
            out[p] = (T["d"][ix][ok], r[ok], T["pts"][ix][ok])
    return out


def rank_before(rs: dict, pid: str, d: int, window: int = RANK_BEFORE) -> tuple[float, float, int] | None:
    """(rank, points, day) of the latest observation in [d - window, d)."""
    s = rs.get(pid)
    if s is None:
        return None
    i = int(np.searchsorted(s[0], d, side="left")) - 1
    if i < 0 or s[0][i] < d - window:
        return None
    return float(s[1][i]), float(s[2][i]), int(s[0][i])


def rank_near(rs: dict, pid: str, d: int, window: int = RANK_AROUND, before: int | None = None) -> float | None:
    """The rank observed nearest day d within +/- window (observations before `before` only)."""
    s = rs.get(pid)
    if s is None:
        return None
    lo = int(np.searchsorted(s[0], d - window, side="left"))
    hi = int(np.searchsorted(s[0], d + window, side="right"))
    if before is not None:
        hi = min(hi, int(np.searchsorted(s[0], before, side="left")))
    if hi <= lo:
        return None
    k = lo + int(np.argmin(np.abs(s[0][lo:hi] - d)))
    return float(s[1][k])


# ---------------------------------------------------------------------------------------------- ratings at dates

def elo_states(hist: dict, days: list[int]) -> list[dict[str, tuple]]:
    """Elo ratings before each day in `days` (sorted ordinals), one pass: [{pid: (all, hard, clay, grass, n, last)}],
    with the inactivity pull up to the day (as elo.ratings_at)."""
    p = hist.get("params") or {}
    idle, rho = float(p.get("idle_days", 60.0)), float(p.get("rho", 1.0))
    init = hist.get("init") or {}
    rows = hist.get("rows") or []
    state: dict[str, list] = {}
    out = []
    k = 0
    si = {"hard": 1, "clay": 2, "grass": 3}
    for d in days:
        while k < len(rows) and an.day(rows[k][1]).toordinal() < d:
            g = rows[k]
            dd = an.day(g[1]).toordinal()
            for pid, ai, sx, n in ((g[2], 13, 14, g[17]), (g[3], 15, 16, g[18])):
                x = state.get(pid)
                if x is None:
                    v = float(init.get(pid, 1500.0))
                    x = state[pid] = [v, v, v, v, 0, dd]
                x[0] = float(g[ai])
                x[si.get(g[4], 1)] = float(g[sx])
                x[4] = int(n or 0)
                x[5] = dd
            k += 1
        snap = {}
        for pid, x in state.items():
            gap = d - x[5]
            f = rho ** ((gap - idle) / 365.0) if (gap > idle and rho < 1.0) else 1.0
            snap[pid] = tuple(1500.0 + (v - 1500.0) * f for v in x[:4]) + (x[4], x[5])
        out.append(snap)
    return out


def gelo_states(hist: dict, days: list[int]) -> list[dict[str, tuple]]:
    """Game-share Elo before each day: [{pid: (all, hard, clay, grass, n)}] (no inactivity pull, as gelo.ratings_at)."""
    rows = hist.get("rows") or []
    state: dict[str, list] = {}
    out = []
    k = 0
    si = {"hard": 1, "clay": 2, "grass": 3}
    for d in days:
        while k < len(rows) and an.day(rows[k][1]).toordinal() < d:
            g = rows[k]
            for pid, ai, sx, n in ((g[2], 6, 7, g[10]), (g[3], 8, 9, g[11])):
                x = state.setdefault(pid, [0.0, 0.0, 0.0, 0.0, 0])
                x[0] = float(g[ai])
                x[si.get(g[4], 1)] = float(g[sx])
                x[4] = int(n or 0)
            k += 1
        out.append({pid: tuple(x) for pid, x in state.items()})
    return out


def sr_summary(model: dict | None) -> dict | None:
    """{"mu", "new", "players": {pid: [s+r all, hard, clay, grass]}} from a serve/return fit (what the ratings need)."""
    if not model or model.get("players") is None:
        return None
    b = model.get("base") or {}
    out = {}
    for pid, rec in (model.get("players") or {}).items():
        row = []
        for s in ("all",) + an.SURFACES:
            x = rec.get(s) or rec.get("all") or {}
            v = an.fnum(x.get("s"))
            w = an.fnum(x.get("r"))
            row.append(round(v + w, 4) if v is not None and w is not None else None)
        out[pid] = row
    return {"mu": float(b.get("mu", 1.0)), "new": float(b.get("new_s", 0.0)) + float(b.get("new_r", 0.0)), "players": out}


def sr_beta(mu: float) -> float:
    """d logit(chain P(win)) / d(s + r) at an even best-of-three match with base hold logit mu."""
    from oddsmarkets.tennis.models import match_chain as mc
    from oddsmarkets.tennis.models import serve_return as SR
    h = 0.05
    out = []
    for dl in (h, -h):
        pa = SR.point_prob_from_hold(float(_sig(mu + dl / 2)))
        pb = SR.point_prob_from_hold(float(_sig(mu - dl / 2)))
        out.append(float(np.asarray(mc.match_win_prob(np.array([pa]), np.array([pb]), 3, "tb7"))[0]))
    return float((_logit(out[0]) - _logit(out[1])) / (2 * h))


def _backtest_fits(tour: str) -> dict[str, Any]:
    """{through iso: path} of the backtest's monthly score-only fits (the newest file per date)."""
    d = an.cache_root() / "backtest_sr"
    out: dict[str, tuple] = {}
    try:
        for p in d.glob(f"sr_{tour}_*.json"):
            parts = p.stem.split("_")
            if len(parts) < 4:
                continue
            th = parts[2]
            mt = p.stat().st_mtime
            if th not in out or mt > out[th][0]:
                out[th] = (mt, p)
    except OSError:
        return {}
    return {k: v[1] for k, v in out.items()}


def sr_at(td: an.TourData, through: date, fits: dict | None = None) -> dict | None:
    """The serve/return summary of a fit through `through`: the backtest's score-only monthly fit when cached, else
    the build's own cached fit (ace_sr) for that date, else None. Never fits anything (the panel would take hours)."""
    from oddsmarkets.tennis.models import _io
    k = through.isoformat()
    path = (fits or {}).get(k)
    if path is not None:
        mdl = _io.read_json(path)
        if isinstance(mdl, dict):
            return sr_summary(mdl)
    hit = _io.read_json(_io.cache_root() / "ace_sr" / f"{td.tour}_{k}.json")
    if isinstance(hit, dict) and isinstance(hit.get("result"), dict):
        return sr_summary(hit["result"])
    return None


# ---------------------------------------------------------------------------------------------- model rating

def blend_weights(tour: str) -> dict:
    """The fundamental blend's weights: the committed fit's "fundamental" block when the match price carries the
    market-rating term (models/mrating.py; the Value section rates players on results and the model, and sets the
    market against it), else the match price's own weights."""
    from oddsmarkets.tennis.models import _io
    from oddsmarkets.tennis.models import predict as P
    b = P.blend_params(tour)
    f = (_io.read_json(_io.FITTED / f"predict_{_io.tour_key(tour)}.json") or {}).get("fundamental") if b.get("w_mr") else None
    if isinstance(f, dict) and f.get("w_elo") is not None:
        b = f
    return {"w_elo": float(b.get("w_elo", 0.6)), "w_sr": float(b.get("w_sr", 0.4)), "w_gelo": float(b.get("w_gelo", 0.0))}


def ratings_for(pids, elo: dict, gelo: dict, sr: dict | None, w: dict, beta: float, elo_w: float, gelo_w: float,
                surface: str | None = None) -> dict[str, float]:
    """Model rating R (Elo scale, before the display offset) for each pid with an Elo rating."""
    si = {"hard": 1, "clay": 2, "grass": 3}
    out = {}
    srp = (sr or {}).get("players") or {}
    new = (sr or {}).get("new", 0.0)
    for p in pids:
        e = elo.get(p)
        if e is None:
            continue
        g = gelo.get(p)
        if surface is None:
            E = e[0]
            G = g[0] if g else 0.0
            S = (srp.get(p) or [None])[0]
        else:
            k = si[surface]
            E = elo_w * e[k] + (1 - elo_w) * e[0]
            G = (gelo_w * g[k] + (1 - gelo_w) * g[0]) if g else 0.0
            S = (srp.get(p) or [None, None, None, None])[k]
        if S is None:
            S = new if sr else 0.0
        out[p] = w["w_elo"] * E + K_ELO * (w["w_sr"] * beta * S + w["w_gelo"] * G)
    return out


def implied_ranks(ranks: dict[str, float], rating: dict[str, float]) -> dict[str, float]:
    """Map the rating order onto the official ranks of the same players: the k-th best rating gets the k-th best
    official rank."""
    common = [p for p in ranks if p in rating]
    if not common:
        return {}
    by_rank = sorted(ranks[p] for p in common)
    by_rating = sorted(common, key=lambda p: (-rating[p], ranks[p]))
    return {p: float(by_rank[i]) for i, p in enumerate(by_rating)}


# ---------------------------------------------------------------------------------------------- event points

def event_points_all(td: an.TourData) -> dict[str, list[tuple[int, int, float, str]]]:
    """{pid: [(end day, drop day, points, event)]} of every counted tour-level event on disk (rankings.event_points)."""
    from oddsmarkets.tennis.analytics import rankings as RK
    out: dict[str, list] = defaultdict(list)
    for y in td.years:
        try:
            pts = RK.event_points(td, y)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s %s event points failed: %s", td.tour, y, exc)
            continue
        for eid, row in pts.items():
            ev = td.events(y).get(eid) or {}
            end = an.day(ev.get("end") or ev.get("start"))
            if end is None:
                continue
            drop = an.day(RK.drop_week(end))
            for p, v in row.items():
                out[str(p)].append((end.toordinal(), drop.toordinal(), float(v), eid))
    for v in out.values():
        v.sort()
    return out


def points_view(ep: list | None, d: int, h: int) -> tuple[float, float, float]:
    """(tour-level points counted at day d, points dropping in (d, d + h], points earned in (d, d + h])."""
    held = drop = earn = 0.0
    for end, dropd, v, _ in ep or ():
        if end < d and dropd > d:
            held += v
            if dropd <= d + h:
                drop += v
        elif d <= end < d + h:
            earn += v
    return held, drop, earn


# ---------------------------------------------------------------------------------------------- luck per match

def luck_params(T: dict) -> dict:
    """Pythagorean exponents (games by best-of; points) and the break-point pressure offsets, fitted on the dev years
    (tour-level main-draw matches through DEV_YEARS[1]) so the published numbers never move with new seasons."""
    yr_hi = date(DEV_YEARS[1], 12, 31).toordinal()
    base = T["tl"] & (T["st"] == 0) & (T["d"] <= yr_hi)
    sh = (T["g"] + 0.5) / (T["g"] + T["gl"] + 1.0)
    out = {}
    for bo in (3, 5):
        sel = base & (T["bo"] == bo) & ((T["g"] + T["gl"]) > 0)
        if sel.sum() < 200:                              # few dev-year matches (tests, a young tour): use every year
            sel = T["tl"] & (T["st"] == 0) & (T["bo"] == bo) & ((T["g"] + T["gl"]) > 0)
        k = fit_k(_logit(sh[sel]), T["won"][sel]) if sel.sum() >= 50 else float("nan")
        out[f"k_games_bo{bo}"] = k if k == k else 7.0
    sel = T["tl"] & (T["st"] == 0) & np.isfinite(T["tpw"])
    k = fit_k(_logit(T["tpw"][sel]), T["won"][sel], 20.0) if sel.sum() >= 50 else float("nan")
    out["k_points"] = k if k == k else 25.0
    m = T["tl"] & np.isfinite(T["bpf"]) & np.isfinite(T["bps"]) & np.isfinite(T["spw"]) & (T["bpf"] > 0)
    out["bp_save_offset"] = float((T["bps"][m].sum() - (T["bpf"][m] * T["spw"][m]).sum()) / T["bpf"][m].sum()) if m.sum() > 50 else 0.0
    m = T["tl"] & np.isfinite(T["bpo"]) & np.isfinite(T["bpc"]) & np.isfinite(T["rpw"]) & (T["bpo"] > 0)
    out["bp_conv_offset"] = float((T["bpc"][m].sum() - (T["bpo"][m] * T["rpw"][m]).sum()) / T["bpo"][m].sum()) if m.sum() > 50 else 0.0
    out["n_games_fit"] = int(base.sum())
    return out


QUANTS = np.linspace(0.05, 0.95, 19)


def typical_opponents(T: dict) -> dict[tuple, dict]:
    """{(year, level, round, band): {"q": quantiles of (opponent Elo - the event's field strength), "mean": mean opponent
    Elo}} from the tour-level matches of the years before `year` (the first years fall back to their own matches).
    Draw luck compares a player's actual opponent with this distribution (relative to the field of the event she
    entered); the strength of schedule compares the opponent with the absolute mean (event choice included)."""
    sel = (T["tl"] & (T["st"] != 3) & np.isin(T["lvl"], LEVEL_GROUPS) & np.isfinite(T["eo"]) & np.isfinite(T["fe"])
           & (T["band"] >= 0))
    years = np.array([date.fromordinal(int(d)).year for d in T["d"][sel]])
    keys = list(zip(T["lvl"][sel], T["rnd"][sel], T["band"][sel].tolist()))
    rel = (T["eo"] - T["fe"])[sel]
    eo = T["eo"][sel]
    per: dict[int, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))
    for y, k, v, a in zip(years, keys, rel, eo):
        per[int(y)][k].append((v, a))
    out: dict[tuple, dict] = {}
    cum: dict[tuple, list] = defaultdict(list)
    for y in sorted(per):
        for k, cur in per[y].items():
            ref = cum.get(k) if len(cum.get(k) or ()) >= 40 else None
            src = ref if ref is not None else (cur if len(cur) >= 10 else None)
            if src is None:
                continue
            arr = np.array(src)
            out[(y,) + k] = {"q": np.quantile(arr[:, 0], QUANTS), "mean": float(arr[:, 1].mean())}
        for k, cur in per[y].items():
            cum[k].extend(cur)
    return out


def _set_win_prob(p_match: float, bo: int) -> float:
    """The per-set win probability q that gives P(win the match) = p_match in a best-of-bo match of independent sets."""
    need = 2 if bo == 3 else 3
    lo, hi = 1e-6, 1 - 1e-6
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if _from_sets(mid, 0, 0, need) < p_match:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _from_sets(q: float, a: int, b: int, need: int) -> float:
    """P(reaching `need` sets first from a-b) with independent sets won with probability q."""
    if a >= need:
        return 1.0
    if b >= need:
        return 0.0
    return q * _from_sets(q, a + 1, b, need) + (1 - q) * _from_sets(q, a, b + 1, need)


def match_luck(T: dict, prm: dict, typ: dict) -> dict[str, np.ndarray]:
    """Per-row luck pieces (NaN where they do not apply): pg = P(win | games share) on completed matches, pp = P(win |
    points share) where statistics exist, draw = Elo P v the opponent - mean Elo P v the typical opponents of that level,
    round and seed band relative to the event's field, sos = opponent Elo - the typical opponent's, free = the value of
    a walkover or an opponent's retirement (1 - P(win at the stoppage)), x_bps / x_bpc = expected break points saved /
    converted."""
    n = T["n"]
    tot = T["g"] + T["gl"]
    sh = (T["g"] + 0.5) / (tot + 1.0)
    k = np.where(T["bo"] == 5, prm["k_games_bo5"], prm["k_games_bo3"])
    pg = np.where((T["st"] == 0) & (tot > 0), pyth(sh, k), np.nan)
    pp = np.where((T["st"] == 0) & np.isfinite(T["tpw"]), pyth(T["tpw"], prm["k_points"]), np.nan)
    draw = np.full(n, np.nan)
    sos = np.full(n, np.nan)
    years = np.array([date.fromordinal(int(d)).year for d in T["d"]])
    f5 = np.where(T["bo"] == 5, float(T.get("f5", 1.0)), 1.0)
    for i in np.nonzero(T["tl"] & (T["st"] != 3) & (T["band"] >= 0) & np.isfinite(T["em"]) & np.isfinite(T["eo"])
                        & np.isfinite(T["fe"]))[0]:
        ref = typ.get((int(years[i]), T["lvl"][i], T["rnd"][i], int(T["band"][i])))
        if ref is None:
            continue
        typ_p = float(np.mean(1.0 / (1.0 + 10.0 ** (-f5[i] * (T["em"][i] - T["fe"][i] - ref["q"]) / 400.0))))
        draw[i] = elo_p(T["em"][i] - T["eo"][i], f5[i]) - typ_p
        sos[i] = T["eo"][i] - ref["mean"]
    free = np.full(n, np.nan)
    for i in np.nonzero(T["won"].astype(bool) & (T["st"] != 0))[0]:
        p = T["ep"][i]
        if not p == p:
            continue
        if T["st"][i] == 3:
            free[i] = 1.0 - p
        else:
            need = 3 if T["bo"][i] == 5 else 2
            q = _set_win_prob(float(p), int(T["bo"][i]))
            free[i] = 1.0 - _from_sets(q, int(min(T["sw"][i], need - 1)), int(min(T["sl"][i], need - 1)), need)
    x_bps = np.where(np.isfinite(T["bpf"]) & np.isfinite(T["spw"]), T["bpf"] * np.clip(T["spw"] + prm["bp_save_offset"], 0, 1), np.nan)
    x_bpc = np.where(np.isfinite(T["bpo"]) & np.isfinite(T["rpw"]), T["bpo"] * np.clip(T["rpw"] + prm["bp_conv_offset"], 0, 1), np.nan)
    return {"pg": pg, "pp": pp, "draw": draw, "sos": sos, "free": free, "x_bps": x_bps, "x_bpc": x_bpc}


def chain_clutch(entries: dict[int, dict] | None) -> dict[str, dict[str, list]]:
    """{pid: {"tb": [(day, won, exp)], "dec": [(day, won, exp)]}} from the catalogue's season entries (the chain's
    tiebreak and deciding-set expectations under each season's serve/return fit)."""
    out: dict[str, dict[str, list]] = defaultdict(lambda: {"tb": [], "dec": []})
    for y, E in (entries or {}).items():
        for pid, lst in (E or {}).items():
            for e in lst:
                d = an.day(e.get("date"))
                if d is None:
                    continue
                dd = d.toordinal()
                for won, ex in e.get("tbs") or ():
                    if ex is not None:
                        out[pid]["tb"].append((dd, bool(won), float(ex)))
                dec = e.get("dec")
                if dec is not None and dec[1] is not None:
                    out[pid]["dec"].append((dd, bool(dec[0]), float(dec[1])))
    return out


def luck_window(T: dict, L: dict, ix: np.ndarray, lo: int, hi: int, clutch: dict | None = None) -> dict:
    """Luck components of one player over rows ix with day in [lo, hi) (tour-level main draw; free wins also from
    walkovers)."""
    d = T["d"][ix]
    w = (d >= lo) & (d < hi)
    tl = T["tl"][ix] & w
    played = tl & (T["st"][ix] != 3)
    done = tl & (T["st"][ix] == 0)
    won = T["won"][ix]
    n = int(played.sum())
    wins = int(won[played].sum())
    pg = L["pg"][ix]
    pp = L["pp"][ix]
    gsel = done & np.isfinite(pg)
    close = float(won[gsel].sum() - pg[gsel].sum()) if gsel.any() else None
    psel = done & np.isfinite(pp) & np.isfinite(pg)
    conv = float(pg[psel].sum() - pp[psel].sum()) if psel.any() else None
    sc = L["draw"][ix]
    ssel = played & np.isfinite(sc)
    draw = float(sc[ssel].sum()) if ssel.any() else 0.0
    so = L["sos"][ix]
    osel = played & np.isfinite(so)
    sos = float(so[osel].mean()) if osel.any() else None
    fr = L["free"][ix]
    fsel = tl & np.isfinite(fr)
    free = float(fr[fsel].sum()) if fsel.any() else 0.0
    n_wo = int((fsel & (T["st"][ix] == 3)).sum())
    n_ret = int((fsel & (T["st"][ix] != 3)).sum())
    out = {"n": n, "w": wins, "l": n - wins, "win_pct": wins / n if n else None, "n_done": int(gsel.sum()),
           "exp_games": float(pg[gsel].sum()) if gsel.any() else None, "close": close,
           "n_stats": int(psel.sum()), "exp_points": float(pp[psel].sum()) if psel.any() else None, "conv": conv,
           "draw": draw, "sos": sos, "free": free, "wo_rec": n_wo, "ret_rec": n_ret,
           "games_share": float(T["g"][ix][gsel].sum() / max(1, (T["g"][ix][gsel] + T["gl"][ix][gsel]).sum())) if gsel.any() else None,
           "points_share": float(np.nanmean(T["tpw"][ix][psel])) if psel.any() else None}
    bsel = tl & np.isfinite(L["x_bps"][ix]) & np.isfinite(T["bps"][ix])
    if bsel.any():
        out.update(bp_saved=float(T["bps"][ix][bsel].sum()), bp_faced=float(T["bpf"][ix][bsel].sum()),
                   bp_saved_exp=float(L["x_bps"][ix][bsel].sum()))
        out["bp_saved_over"] = out["bp_saved"] - out["bp_saved_exp"]
    csel = tl & np.isfinite(L["x_bpc"][ix]) & np.isfinite(T["bpc"][ix])
    if csel.any():
        out.update(bp_conv=float(T["bpc"][ix][csel].sum()), bp_opps=float(T["bpo"][ix][csel].sum()),
                   bp_conv_exp=float(L["x_bpc"][ix][csel].sum()))
        out["bp_conv_over"] = out["bp_conv"] - out["bp_conv_exp"]
    if clutch is not None:
        for k in ("tb", "dec"):
            lst = [x for x in clutch.get(k) or () if lo <= x[0] < hi]
            if lst:
                wv = sum(1 for x in lst if x[1])
                ex = sum(x[2] for x in lst)
                out[k] = {"w": wv, "l": len(lst) - wv, "exp": ex, "over": wv - ex}
    # point-to-game conversion (WTA) is shown but left out of the total: it persists from season to season (it is
    # partly how a player's serve and return points turn into games), so it is not treated as luck
    out["total"] = (close or 0.0) + draw + free
    out["adj_win_pct"] = (wins - (close or 0.0) - draw) / n if n else None
    return out


# ---------------------------------------------------------------------------------------------- snapshot features

def snapshot_days(tour: str, today: date) -> list[date]:
    out = []
    for y in range(FIRST_SNAP.get(tour, 2008), today.year + 1):
        for mth in SNAP_MONTHS:
            t = date(y, mth, 1)
            if t <= today:
                out.append(t)
    return out


def quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


class Ctx:
    """What the feature builder needs for one tour: the match table, rank series, event points, luck pieces, dates of
    birth (no arrays referenced from closures; plain attributes freed with the object)."""

    def __init__(self, td: an.TourData, T: dict | None = None):
        self.td = td
        self.T = T if T is not None else match_table(td)
        self.rs = rank_series(self.T)
        self.ep = event_points_all(td)
        self.lp = luck_params(self.T)
        self.typ = typical_opponents(self.T)
        self.L = match_luck(self.T, self.lp, self.typ)
        self.dob = {p: an.day(x.get("dob")) for p, x in td.players.items() if x.get("dob")}
        self.dob_from = {p: td.dob_from(p) for p in self.dob}
        self.w = blend_weights(td.tour)
        prm = td.elo_params() or {}
        self.elo_w = float(prm.get("w_surf", 0.5))
        gp = (td.gelo.get("params") or {})
        self.gelo_w = float(gp.get("w_surf", 0.3))
        self.f5 = float(prm.get("bo5", 1.0))


def features_at(C: Ctx, t: date, ranks: dict[str, tuple[float, float]], elo: dict, gelo: dict, sr: dict | None,
                elo_6m: dict, beta: float, h_days: dict[str, int] | None = None) -> dict[str, dict]:
    """Feature rows {pid: {...}} at day t for the players in `ranks` ({pid: (rank, points)}). `elo_6m` is the Elo state
    six months earlier (the trend). Raw values (not standardised); FEATURES lists the model's inputs."""
    T, L = C.T, C.L
    d = t.toordinal()
    h_days = h_days or HORIZONS
    R = ratings_for(list(ranks), elo, gelo, sr, C.w, beta, C.elo_w, C.gelo_w)
    imp = implied_ranks({p: v[0] for p, v in ranks.items()}, R)
    out = {}
    for p, (rk, pts) in ranks.items():
        if p not in R or p not in elo:
            continue
        e = elo[p]
        ix = C.T["by"].get(p, np.zeros(0, np.int64))
        dd = T["d"][ix]
        past = dd < d
        last12 = past & (dd >= d - 365)
        rated = last12 & (T["st"][ix] != 3)
        n12 = int(rated.sum())
        tl12 = last12 & T["tl"][ix] & (T["st"][ix] != 3)
        done12 = tl12 & (T["st"][ix] == 0) & np.isfinite(L["pg"][ix])
        luck = float((T["won"][ix][done12] - L["pg"][ix][done12]).sum() / max(1, done12.sum())) if done12.any() else 0.0
        sc = tl12 & np.isfinite(L["draw"][ix])
        draw = float(L["draw"][ix][sc].sum() / max(1, tl12.sum())) if sc.any() else 0.0
        mk_sel = rated & np.isfinite(T["book"][ix]) & np.isfinite(T["ep"][ix])
        if mk_sel.any():
            f = np.where(T["bo"][ix][mk_sel] == 5, C.f5, 1.0)
            gapm = (_logit(T["book"][ix][mk_sel]) - _logit(T["ep"][ix][mk_sel])) * K_ELO / f
            nm = int(mk_sel.sum())
            mk = float(np.mean(gapm)) * nm / (nm + 10.0) / 100.0
        else:
            mk = 0.0
        last_day = int(dd[past & (T["st"][ix] != 3)].max()) if (past & (T["st"][ix] != 3)).any() else None
        idle = (d - last_day) if last_day is not None else 365
        dob = C.dob.get(p)
        age = an.age_at(dob, t, C.dob_from.get(p))
        e6 = elo_6m.get(p)
        rk6 = rank_near(C.rs, p, d - 182, RANK_AROUND, before=d)
        held, drop12, _ = points_view(C.ep.get(p), d, h_days["12m"])
        _, drop6, _ = points_view(C.ep.get(p), d, h_days["6m"])
        pts_ = pts if (pts == pts and pts and pts > 0) else None
        gap = math.log(rk) - math.log(imp[p]) if p in imp else 0.0
        row = {"rank": rk, "pts": pts_, "R": R[p], "imp": imp.get(p), "gap_raw": gap, "n12": n12, "elo": e[0],
               "elo_n": e[4], "age": age, "idle": idle, "d_elo": (e[0] - e6[0]) / 100.0 if e6 else 0.0,
               "d_rank": (math.log(rk) - math.log(rk6)) if rk6 else 0.0, "held": held, "drop12": drop12, "drop6": drop6,
               "luck": luck, "draw": draw, "mk": mk, "tl12": int(tl12.sum()), "g": (gelo.get(p) or (0.0,))[0],
               "sr": ((sr or {}).get("players") or {}).get(p, [None])[0]}
        out[p] = row
    return out


def design(rows: list[dict], h: str, k_shrink: float) -> np.ndarray:
    """The model matrix (FKEYS columns, raw) for feature rows at horizon h ("12m" / "6m")."""
    X = np.full((len(rows), len(FKEYS)), np.nan)
    for i, r in enumerate(rows):
        pts = r.get("pts") or None
        drop = r["drop12"] if h == "12m" else r["drop6"]
        age = r.get("age")
        vals = {"lr": math.log(r["rank"]), "gap": r["gap_raw"] * r["n12"] / (r["n12"] + k_shrink) if (r["n12"] + k_shrink) > 0 else 0.0,
                "age": (age - 25.0) if age is not None else np.nan, "age2": ((age - 25.0) ** 2 / 10.0) if age is not None else np.nan,
                "age_na": 0.0 if age is not None else 1.0, "d_elo": r["d_elo"], "d_rank": r["d_rank"],
                "idle": math.log1p(max(0, r["idle"])), "n12": math.log1p(r["n12"]),
                "drop": min(2.0, drop / pts) if pts else np.nan, "tl": min(2.0, r["held"] / pts) if pts else np.nan,
                "luck": r["luck"], "draw": r["draw"], "mk": r["mk"]}
        X[i] = [vals[k] for k in FKEYS]
    return X


# ---------------------------------------------------------------------------------------------- ridge and logistic

class Ridge:
    """Ridge regression on standardised columns (missing values -> the training mean, i.e. 0 after scaling)."""

    def __init__(self, lam: float = 10.0, cols: list[int] | None = None):
        self.lam, self.cols = float(lam), cols

    def fit(self, X: np.ndarray, y: np.ndarray) -> "Ridge":
        X = X if self.cols is None else X[:, self.cols]
        ok = np.isfinite(X)
        cnt = ok.sum(axis=0)
        self.mu = np.where(cnt > 0, np.where(ok, X, 0.0).sum(axis=0) / np.maximum(cnt, 1), 0.0)
        Z = np.where(np.isfinite(X), X, self.mu) - self.mu
        self.sd = Z.std(axis=0)
        self.sd = np.where(self.sd > 1e-9, self.sd, 1.0)
        Z = Z / self.sd
        self.b0 = float(np.mean(y))
        A = Z.T @ Z + self.lam * np.eye(Z.shape[1])
        self.b = np.linalg.solve(A, Z.T @ (y - self.b0))
        return self

    def z(self, X: np.ndarray) -> np.ndarray:
        X = X if self.cols is None else X[:, self.cols]
        return (np.where(np.isfinite(X), X, self.mu) - self.mu) / self.sd

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.b0 + self.z(X) @ self.b

    def contrib(self, X: np.ndarray) -> np.ndarray:
        """Per-feature contributions (log-rank units) relative to the average training row."""
        return self.z(X) * self.b


def logistic(X: np.ndarray, y: np.ndarray, lam: float = 1.0) -> np.ndarray:
    """Ridge logistic regression with an intercept (columns already scaled); returns [b0, b...]."""
    Xa = np.column_stack([np.ones(len(X)), X])
    b = np.zeros(Xa.shape[1])
    pen = np.full(Xa.shape[1], lam)
    pen[0] = 0.0
    for _ in range(50):
        p = _sig(Xa @ b)
        g = Xa.T @ (y - p) - pen * b
        H = (Xa * (p * (1 - p))[:, None]).T @ Xa + np.diag(pen) + 1e-9 * np.eye(len(b))
        step = np.linalg.solve(H, g)
        b += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return b


def logistic_p(b: np.ndarray, X: np.ndarray) -> np.ndarray:
    return _sig(b[0] + X @ b[1:])


# ---------------------------------------------------------------------------------------------- the panel

def build_panel(C: Ctx, asof: date) -> dict:
    """Historical snapshot rows with features and targets (only targets whose window closed before `asof`).
    {"rows": [...], "snapshots": [iso], "coverage": {iso: {"n", "obs12", "obs6"}}, "beta": ..., "sr_dates": n}"""
    td = C.td
    days = [t for t in snapshot_days(td.tour, asof) if t < asof]
    all_days = sorted({t.toordinal() for t in days} | {(t - timedelta(days=182)).toordinal() for t in days}
                      | {(t + timedelta(days=h)).toordinal() for t in days for h in HORIZONS.values()})
    est = elo_states(td.elo, all_days)
    gst = gelo_states(td.gelo, all_days)
    E = dict(zip(all_days, est))
    G = dict(zip(all_days, gst))
    fits = _backtest_fits(td.tour)
    beta = None
    rows = []
    cover = {}
    cutoff = asof.toordinal()
    for t in days:
        d = t.toordinal()
        ranks = {}
        for p in C.rs:
            rb = rank_before(C.rs, p, d)
            if rb is not None and rb[0] <= UNIVERSE:
                ranks[p] = (rb[0], rb[1])
        if len(ranks) < 20:
            continue
        sr = sr_at(td, t - timedelta(days=1), fits)
        if sr is not None and beta is None:
            beta = sr_beta(sr["mu"])
        b = beta if beta is not None else 0.7
        feats = features_at(C, t, ranks, E[d], G[d], sr, E[(t - timedelta(days=182)).toordinal()], b)
        cv = {"n": len(feats), "sr": sr is not None}
        for h, hd in HORIZONS.items():
            tgt = d + hd
            closed = tgt + RANK_AROUND <= cutoff
            obs = 0
            et = E.get(tgt) or {}
            for p, r in feats.items():
                if not closed:
                    r[f"y{h}"] = None
                    r[f"o{h}"] = None
                    r[f"e{h}"] = None
                    continue
                r[f"earn{h}"] = points_view(C.ep.get(p), d, hd)[2]
                rk = rank_near(C.rs, p, tgt, RANK_AROUND, before=cutoff)
                r[f"o{h}"] = 1 if rk is not None else 0
                r[f"y{h}"] = math.log(rk) - math.log(r["rank"]) if rk is not None else None
                r[f"r{h}"] = rk
                x = et.get(p)
                r[f"e{h}"] = (x[0] - r["elo"]) if x else None
                obs += 1 if rk is not None else 0
            cv[f"obs{h}"] = obs if closed else None
        cover[t.isoformat()] = cv
        for p, r in feats.items():
            r["pid"] = p
            r["t"] = t.isoformat()
            rows.append(r)
    return {"rows": rows, "coverage": cover, "beta": beta, "sr_fits": len(fits)}


def _usable(r: dict, h: str, coverage: dict) -> bool:
    """A row whose target window closed and whose snapshot observed at least half its universe at the target (the 2020
    tour stoppage leaves whole snapshots unobserved)."""
    cv = coverage.get(r["t"]) or {}
    ob = cv.get(f"obs{h}")
    return r.get(f"o{h}") is not None and ob is not None and ob >= 0.5 * max(1, cv.get("n") or 0)


def _year(r: dict) -> int:
    return int(r["t"][:4])


def walk_forward(panel: dict, h: str, k_shrink: float, lam: float, cols: list[str] | None = None,
                 years: tuple[int, int] | None = None, tour: str = "atp") -> list[dict]:
    """Predictions for every usable row of the prediction years, the model refitted each year on the rows whose target
    window closed before 1 January of that year. Returns the test rows with "pred" (and "pred_elo")."""
    rows = [r for r in panel["rows"] if _usable(r, h, panel["coverage"])]
    if not rows:
        return []
    hd = HORIZONS[h]
    X = design(rows, h, k_shrink)
    y = np.array([r[f"y{h}"] if r[f"y{h}"] is not None else np.nan for r in rows], float)
    ye = np.array([r[f"e{h}"] if r.get(f"e{h}") is not None else np.nan for r in rows], float)
    tday = np.array([date.fromisoformat(r["t"]).toordinal() for r in rows])
    yrs = np.array([_year(r) for r in rows])
    ci = [FKEYS.index(c) for c in (cols or FKEYS)]
    lo_y = FIRST_PRED_YEAR.get(tour, 2010)
    y0, y1 = years or (lo_y, int(yrs.max()))
    out = []
    for Y in range(max(y0, lo_y), y1 + 1):
        test = yrs == Y
        if not test.any():
            continue
        cut = date(Y, 1, 1).toordinal()
        train = (tday + hd + RANK_AROUND <= cut) & np.isfinite(y)
        if train.sum() < 150:
            continue
        m = Ridge(lam, ci).fit(X[train], y[train])
        pred = m.predict(X[test])
        tre = train & np.isfinite(ye)
        me = Ridge(lam, ci).fit(X[tre], ye[tre]) if tre.sum() >= 150 else None
        pe = me.predict(X[test]) if me is not None else np.full(test.sum(), np.nan)
        # breakout / regression probabilities: logistic on (distance of the prediction from the event's threshold at
        # this rank, log rank), fitted on the training rows' in-sample predictions (the ridge has 14 parameters on
        # thousands of rows); every training row counts, unobserved ones as regressions
        all_tr = (tday + hd + RANK_AROUND <= cut)
        rows_all = np.nonzero(all_tr)[0]
        ptr_all = m.predict(X[all_tr])
        yy = np.array([rows[i][f"y{h}"] if rows[i][f"y{h}"] is not None else np.nan for i in rows_all])
        rk_all = np.array([rows[i]["rank"] for i in rows_all], float)
        rise_all, fall_all = _events(yy, rk_all)
        sc = _prob_scale(ptr_all, rk_all)
        Zr, Zf = _prob_z(ptr_all, rk_all, sc)
        b_rise = logistic(Zr, rise_all.astype(float))
        b_fall = logistic(Zf, fall_all.astype(float))
        rk_te = np.array([rows[i]["rank"] for i in np.nonzero(test)[0]], float)
        Zr_t, Zf_t = _prob_z(pred, rk_te, sc)
        pr, pf = logistic_p(b_rise, Zr_t), logistic_p(b_fall, Zf_t)
        for j, i in enumerate(np.nonzero(test)[0]):
            r = rows[i]
            out.append({"pid": r["pid"], "t": r["t"], "year": Y, "rank": r["rank"], "y": r[f"y{h}"], "obs": r[f"o{h}"],
                        "pred": float(pred[j]), "ye": r.get(f"e{h}"), "pred_e": float(pe[j]), "p_rise": float(pr[j]),
                        "p_fall": float(pf[j]), "age": r.get("age")})
    return out


def _events(y: np.ndarray, rank: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(breakout, regression) flags: a rise of a third or more (and RISE_PLACES places); a fall by half or more (and
    RISE_PLACES places: No. 1 to No. 2 is not a regression), or no
    rank observed at the target (dropped out of tour-level main draws)."""
    y = np.asarray(y, float)
    obs = np.isfinite(y)
    yy = np.where(obs, y, 0.0)
    new = rank * np.exp(yy)
    rise = obs & (yy <= RISE) & (rank - new >= RISE_PLACES)
    fall = (~obs) | ((yy >= FALL) & (new - rank >= RISE_PLACES))
    return rise, fall


def thresholds(rank) -> tuple[np.ndarray, np.ndarray]:
    """The log-rank changes that make a breakout and a regression at each rank: min(RISE, log((rank - 5) / rank)) and
    max(FALL, log((rank + 5) / rank)) (No. 1 must reach No. 6 to have regressed)."""
    rank = np.asarray(rank, float)
    up = np.where(rank > RISE_PLACES + 1, np.minimum(RISE, np.log(np.maximum(rank - RISE_PLACES, 1e-9) / rank)), RISE)
    down = np.maximum(FALL, np.log((rank + RISE_PLACES) / rank))
    return up, down


def _prob_raw(pred, rank) -> tuple[np.ndarray, np.ndarray]:
    up, down = thresholds(rank)
    lr = np.log(np.asarray(rank, float))
    pred = np.asarray(pred, float)
    return np.column_stack([pred - up, lr]), np.column_stack([pred - down, lr])


def _prob_scale(pred, rank) -> dict:
    out = {}
    for k, M in zip(("rise", "fall"), _prob_raw(pred, rank)):
        out[k] = [float(M[:, 0].mean()), float(M[:, 0].std() or 1.0), float(M[:, 1].mean()), float(M[:, 1].std() or 1.0)]
    return out


def _prob_z(pred, rank, sc: dict) -> tuple[np.ndarray, np.ndarray]:
    """Standardised (distance from the threshold, log rank) for the breakout and the regression layers."""
    out = []
    for k, M in zip(("rise", "fall"), _prob_raw(pred, rank)):
        c = sc[k]
        out.append(np.column_stack([(M[:, 0] - c[0]) / c[1], (M[:, 1] - c[2]) / c[3]]))
    return out[0], out[1]


def tune(panel: dict, tour: str) -> dict:
    """lambda and the shrinkage constant by mean Spearman correlation on the dev years (12-month horizon)."""
    best = None
    grid = []
    for k in SHRINK_K:
        for lam in LAMBDAS:
            pr = walk_forward(panel, "12m", k, lam, None, DEV_YEARS, tour)
            obs = [r for r in pr if r["y"] is not None]
            if len(obs) < 100:
                continue
            per = defaultdict(list)
            for r in obs:
                per[r["year"]].append(r)
            rho = float(np.mean([spearman([r["pred"] for r in v], [r["y"] for r in v]) for v in per.values()]))
            grid.append([k, lam, round(rho, 4)])
            if best is None or rho > best[2]:
                best = (k, lam, rho)
    if best is None:
        return {"k_shrink": 10.0, "lam": 100.0, "grid": grid, "dev_rho": None}
    return {"k_shrink": best[0], "lam": best[1], "grid": grid, "dev_rho": round(best[2], 4)}


def evaluate(pr: list[dict], pr_base: dict[str, list[dict]]) -> dict:
    """Per-year and pooled (dev, test) scores of walk-forward predictions with player-cluster bootstrap CIs."""
    def block(rows: list[dict], base: dict[str, list[dict]], seed: int) -> dict:
        obs = [r for r in rows if r["y"] is not None]
        if len(obs) < 20:
            return {"n": len(rows), "n_obs": len(obs)}
        g = np.array([r["pid"] for r in obs])
        rho = boot_ci(spearman, g, np.array([r["pred"] for r in obs]), np.array([r["y"] for r in obs]), seed=seed)
        out = {"n": len(rows), "n_obs": len(obs), "rho": [r3(x) for x in rho]}
        eo = [r for r in rows if r.get("ye") is not None and r.get("pred_e") == r.get("pred_e")]
        if len(eo) >= 20:
            ge = np.array([r["pid"] for r in eo])
            out["rho_elo"] = [r3(x) for x in boot_ci(spearman, ge, np.array([r["pred_e"] for r in eo]),
                                                       np.array([r["ye"] for r in eo]), seed=seed + 1)]
        for name, brows in base.items():
            keyset = {(r["pid"], r["t"]) for r in obs}
            bo = [r for r in brows if (r["pid"], r["t"]) in keyset and r["y"] is not None]
            if len(bo) >= 20:
                out[f"rho_{name}"] = r3(spearman([r["pred"] for r in bo], [r["y"] for r in bo]))
                # paired difference full - baseline
                bmap = {(r["pid"], r["t"]): r["pred"] for r in bo}
                pair = [r for r in obs if (r["pid"], r["t"]) in bmap]
                if len(pair) >= 20:
                    gp = np.array([r["pid"] for r in pair])
                    a = np.array([r["pred"] for r in pair])
                    bb = np.array([bmap[(r["pid"], r["t"])] for r in pair])
                    yv = np.array([r["y"] for r in pair])
                    out[f"d_{name}"] = [r3(x) for x in boot_ci(lambda a_, b_, y_: spearman(a_, y_) - spearman(b_, y_), gp, a, bb, yv,
                                                               seed=seed + 2)]
        # top-N lists per snapshot: hit rates against base rates
        by_t: dict[str, list] = defaultdict(list)
        for r in rows:
            by_t[r["t"]].append(r)
        hits_r = hits_f = n_r = n_f = 0
        base_r = base_f = n_all = 0
        rec_num = rec_den = 0
        brier_r = brier_r0 = brier_f = brier_f0 = 0.0
        nb = 0
        for t, lst in by_t.items():
            yv = np.array([r["y"] if r["y"] is not None else np.nan for r in lst], float)
            rk = np.array([r["rank"] for r in lst], float)
            rise, fall = _events(yv, rk)
            cand = rk > 10                              # a top-10 player cannot "break out"
            # the lists the page shows: the most likely breakouts (outside the top 10) and regressions
            p_r0 = np.array([r["p_rise"] for r in lst])
            p_f0 = np.array([r["p_fall"] for r in lst])
            order_r = [i for i in np.argsort(-p_r0, kind="stable") if cand[i]][:TOP_N]
            order_f = list(np.argsort(-p_f0, kind="stable"))[:TOP_N]
            hits_r += int(rise[order_r].sum())
            n_r += len(order_r)
            hits_f += int(fall[order_f].sum())
            n_f += len(order_f)
            base_r += int(rise[cand].sum())
            n_all += int(cand.sum())
            base_f += int(fall.sum())
            rec_num += int(rise[order_r].sum())
            rec_den += int(rise[cand].sum())
            p_r = np.array([r["p_rise"] for r in lst])
            p_f = np.array([r["p_fall"] for r in lst])
            br = float(np.mean(rise[cand])) if cand.any() else 0.0
            bf = float(np.mean(fall))
            brier_r += float(np.sum((p_r[cand] - rise[cand]) ** 2))
            brier_r0 += float(np.sum((br - rise[cand]) ** 2))
            brier_f += float(np.sum((p_f - fall) ** 2))
            brier_f0 += float(np.sum((bf - fall) ** 2))
            nb += int(cand.sum())
        n_fall_all = sum(len(v) for v in by_t.values())
        out["risers"] = {"hit": r3(hits_r / n_r) if n_r else None, "base": r3(base_r / n_all) if n_all else None,
                         "lift": r3((hits_r / n_r) / (base_r / n_all)) if n_r and base_r else None, "n": n_r,
                         "recall": r3(rec_num / rec_den) if rec_den else None}
        out["fallers"] = {"hit": r3(hits_f / n_f) if n_f else None, "base": r3(base_f / n_fall_all) if n_fall_all else None,
                          "lift": r3((hits_f / n_f) / (base_f / n_fall_all)) if n_f and base_f else None, "n": n_f}
        out["brier_rise"] = [r3(brier_r / nb, 4), r3(brier_r0 / nb, 4)] if nb else None
        out["brier_fall"] = [r3(brier_f / n_fall_all, 4), r3(brier_f0 / n_fall_all, 4)] if n_fall_all else None
        return out

    years = sorted({r["year"] for r in pr})
    per_year = {}
    for k, Y in enumerate(years):
        per_year[str(Y)] = block([r for r in pr if r["year"] == Y], {n: [r for r in b if r["year"] == Y] for n, b in pr_base.items()}, 100 + k)
    pooled = {}
    for name, (a, b) in (("dev", DEV_YEARS), ("test", TEST_YEARS)):
        pooled[name] = block([r for r in pr if a <= r["year"] <= b], {n: [r for r in v if a <= r["year"] <= b] for n, v in pr_base.items()}, 7)
        pooled[name]["years"] = [a, b]
    return {"per_year": per_year, "pooled": pooled}


def age_curve(panel: dict, h: str = "12m") -> list[list]:
    """[[age, n, mean log-rank change, lo, hi, mean Elo change]] by whole year of age (18 or younger ... 34+)."""
    rows = [r for r in panel["rows"] if _usable(r, h, panel["coverage"]) and r.get("age") is not None and r[f"y{h}"] is not None]
    out = []
    for a in range(18, 35):
        sel = [r for r in rows if (int(r["age"]) == a) or (a == 18 and r["age"] < 18) or (a == 34 and r["age"] >= 34)]
        if len(sel) < 15:
            continue
        y = np.array([r[f"y{h}"] for r in sel])
        g = np.array([r["pid"] for r in sel])
        est, lo, hi = boot_ci(lambda v: float(np.mean(v)), g, y, n=200, seed=a)
        ee = [r[f"e{h}"] for r in sel if r.get(f"e{h}") is not None]
        out.append([a, len(sel), r3(est), r3(lo), r3(hi), r3(np.mean(ee), 1) if ee else None])
    return out


# ---------------------------------------------------------------------------------------------- luck evidence

def season_luck(C: Ctx, clutch: dict, years: list[int]) -> dict[int, dict[str, dict]]:
    """{year: {pid: luck_window over the calendar year}} for players with MIN_LUCK+ tour-level matches."""
    out: dict[int, dict] = {}
    for y in years:
        lo, hi = date(y, 1, 1).toordinal(), date(y + 1, 1, 1).toordinal()
        rows = {}
        for p, ix in C.T["by"].items():
            dd = C.T["d"][ix]
            if not ((dd >= lo) & (dd < hi)).any():
                continue
            lw = luck_window(C.T, C.L, ix, lo, hi, clutch.get(p))
            if lw["n"] >= MIN_LUCK:
                rows[p] = lw
        vals = [r["sos"] for r in rows.values() if r.get("sos") is not None]
        mu = float(np.mean(vals)) if vals else 0.0
        for r in rows.values():
            if r.get("sos") is not None:
                r["sos"] -= mu                      # Elo levels drift between years: relative to the season's players
        out[y] = rows
    return out


EVIDENCE = [
    # key, label, kind (luck | skill), per what
    ("close_pm", "Close-match luck per match", "luck"),
    ("tb_pm", "Tiebreaks over expected per tiebreak", "luck"),
    ("dec_pm", "Deciding sets over expected per decider", "luck"),
    ("draw_pm", "Draw luck per match", "luck"),
    ("free_pm", "Free wins per match", "luck"),
    ("conv_pm", "Points-to-games conversion per match (WTA stats; not counted as luck)", "structural"),
    ("bps_pm", "Break points saved over expected per break point (WTA stats)", "luck"),
    ("bpc_pm", "Break points converted over expected per chance (WTA stats)", "luck"),
    ("total_pm", "Wins above expectation per match", "luck"),
    ("win_pct", "Win %", "skill"),
    ("games_share", "Share of games won", "skill"),
    ("sos", "Strength of schedule (opponent Elo v typical)", "schedule"),
    ("points_share", "Share of points won (WTA stats)", "skill"),
]


def _per_match(lw: dict) -> dict:
    n = lw.get("n") or 0
    nd = lw.get("n_done") or 0
    out = {"close_pm": lw["close"] / nd if lw.get("close") is not None and nd else None,
           "draw_pm": lw["draw"] / n if n else None, "free_pm": lw["free"] / n if n else None,
           "sos": lw.get("sos"),
           "conv_pm": lw["conv"] / lw["n_stats"] if lw.get("conv") is not None and (lw.get("n_stats") or 0) >= 10 else None,
           "total_pm": lw["total"] / n if n else None, "win_pct": lw.get("win_pct"), "games_share": lw.get("games_share"),
           "points_share": lw.get("points_share") if (lw.get("n_stats") or 0) >= 10 else None}
    tb = lw.get("tb")
    out["tb_pm"] = tb["over"] / (tb["w"] + tb["l"]) if tb and (tb["w"] + tb["l"]) >= 5 else None
    dc = lw.get("dec")
    out["dec_pm"] = dc["over"] / (dc["w"] + dc["l"]) if dc and (dc["w"] + dc["l"]) >= 4 else None
    out["bps_pm"] = lw["bp_saved_over"] / lw["bp_faced"] if (lw.get("bp_faced") or 0) >= 30 else None
    out["bpc_pm"] = lw["bp_conv_over"] / lw["bp_opps"] if (lw.get("bp_opps") or 0) >= 30 else None
    return out


def luck_evidence(seasons: dict[int, dict[str, dict]]) -> dict:
    """Year-to-year correlations of each luck component (and of skill measures, for contrast), players with
    MIN_EVIDENCE+ matches in both seasons; and next-season win % predicted from raw, Pythagorean and luck-adjusted
    win % (walk-forward linear fits)."""
    years = sorted(seasons)
    pairs = []
    for y in years:
        nxt = seasons.get(y + 1)
        if not nxt:
            continue
        for p, a in seasons[y].items():
            b = nxt.get(p)
            if b is None or a["n"] < MIN_EVIDENCE or b["n"] < MIN_EVIDENCE:
                continue
            pairs.append((y, p, a, b))
    corr = []
    for key, label, kind in EVIDENCE:
        xs, ys, gs = [], [], []
        for y, p, a, b in pairs:
            u, v = _per_match(a).get(key), _per_match(b).get(key)
            if u is None or v is None:
                continue
            xs.append(u)
            ys.append(v)
            gs.append(p)
        if len(xs) < 30:
            continue
        est, lo, hi = boot_ci(pearson, np.array(gs), np.array(xs), np.array(ys), seed=len(corr))
        corr.append({"key": key, "label": label, "kind": kind, "n": len(xs), "r": r3(est), "lo": r3(lo), "hi": r3(hi)})
    # prediction of next season's win %
    pred = []
    if pairs:
        yrs = np.array([q[0] for q in pairs])
        g = np.array([q[1] for q in pairs])
        nxt = np.array([q[3]["win_pct"] for q in pairs], float)
        cand = {"raw": np.array([q[2]["win_pct"] for q in pairs], float),
                "pythagorean": np.array([(q[2]["exp_games"] or 0) / q[2]["n_done"] if q[2].get("n_done") else np.nan for q in pairs], float),
                "luck_adjusted": np.array([q[2]["adj_win_pct"] if q[2].get("adj_win_pct") is not None else np.nan for q in pairs], float)}
        # walk-forward: for each year, a linear fit of next-season win % on the predictor over the earlier pairs
        for name, x in cand.items():
            err, gg = [], []
            for Y in sorted(set(yrs)):
                tr = (yrs < Y) & np.isfinite(x) & np.isfinite(nxt)
                te = (yrs == Y) & np.isfinite(x) & np.isfinite(nxt)
                if tr.sum() < 100 or not te.any():
                    continue
                A = np.column_stack([np.ones(tr.sum()), x[tr]])
                coef = np.linalg.lstsq(A, nxt[tr], rcond=None)[0]
                e = nxt[te] - (coef[0] + coef[1] * x[te])
                err.extend(e.tolist())
                gg.extend(g[te].tolist())
            ok = np.isfinite(x) & np.isfinite(nxt)
            r = boot_ci(pearson, g[ok], x[ok], nxt[ok], seed=11)
            pred.append({"key": name, "n": int(ok.sum()), "r": r3(r[0]), "lo": r3(r[1]), "hi": r3(r[2]),
                         "rmse_wf": r3(math.sqrt(float(np.mean(np.square(err))))) if err else None, "n_wf": len(err)})
        # paired: luck-adjusted minus raw correlation with next season, bootstrap
        ok = np.isfinite(cand["raw"]) & np.isfinite(cand["luck_adjusted"]) & np.isfinite(nxt)
        if ok.sum() > 30:
            d = boot_ci(lambda a, b, c: pearson(b, c) - pearson(a, c), g[ok], cand["raw"][ok], cand["luck_adjusted"][ok], nxt[ok], seed=12)
            pred.append({"key": "adjusted_minus_raw", "n": int(ok.sum()), "r": r3(d[0]), "lo": r3(d[1]), "hi": r3(d[2])})
    return {"pairs": len(pairs), "min_matches": MIN_EVIDENCE, "correlations": corr, "prediction": pred,
            "years": [years[0], years[-1]] if years else None}


# ---------------------------------------------------------------------------------------------- history (cached)

def history_key(td: an.TourData, asof: date) -> str:
    """Inputs of the cached part: the quarter, the completed years' stores, the fits, the dates of birth, the backtest's
    serve/return fits (their count) and this module's version."""
    from oddsmarkets.tennis.models import _io
    sigs = []
    for y in td.years:
        if y >= asof.year:
            continue
        p = an.data_root() / td.tour / str(y) / "store.json"
        try:
            st = p.stat()
            sigs.append([y, st.st_size, st.st_mtime_ns])
        except OSError:
            sigs.append([y, None, None])
    bio = an.data_root() / td.tour / "bio.json"
    return an.digest(VERSION, _source_digest(), td.tour, asof.isoformat(), sigs, _io.fits_signature(td.tour),
                     bio.stat().st_size if bio.exists() else None, len(_backtest_fits(td.tour)))


def _read_source_digest() -> str:
    from pathlib import Path
    try:
        return hashlib.sha1(Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


_SOURCE_DIGEST = _read_source_digest()      # read once, at import: the code this process actually runs


def _source_digest() -> str:
    """This module's source as imported: any change to the code rebuilds the cached history (a process started before
    an edit keeps its own digest, so it never files old results under the new code's key)."""
    return _SOURCE_DIGEST


def history(C: Ctx, entries: dict | None, asof: date) -> dict:
    """The cached heavy part: the snapshot panel, tuning on the dev years, walk-forward validation (both horizons and
    the baselines), the final models on every closed window, the age curve and the luck evidence."""
    td = C.td
    panel = build_panel(C, asof)
    tuned = tune(panel, td.tour)
    k, lam = tuned["k_shrink"], tuned["lam"]
    val = {}
    models = {}
    drop_one = {}
    for h in HORIZONS:
        full = walk_forward(panel, h, k, lam, None, None, td.tour)
        base = {name: walk_forward(panel, h, k, lam, cols, None, td.tour) for name, cols in BASELINES.items() if name != "full"}
        val[h] = evaluate(full, base)
        val[h]["recent"] = _recent_lists(full)
        models[h] = final_model(panel, h, k, lam, asof)
        drop_one[h] = _drop_one(panel, h, k, lam, td.tour, full)
    clutch = chain_clutch(entries)
    years = sorted({int(y) for y in (entries or {}).keys()} | set(td.years))
    seasons = season_luck(C, clutch, [y for y in years if y < asof.year])
    evid = luck_evidence(seasons)
    cov = panel["coverage"]
    return {"version": VERSION, "asof": asof.isoformat(), "tuned": tuned, "validation": val, "models": models,
            "drop_one": drop_one, "earn_bins": {h: earn_bins([r for r in panel["rows"] if _usable(r, h, panel["coverage"])], h) for h in HORIZONS},
            "age_curve": age_curve(panel), "luck_params": C.lp, "luck_evidence": evid, "beta": panel.get("beta"),
            "panel": {"rows": len(panel["rows"]), "snapshots": len(cov),
                      "first": min(cov) if cov else None, "last": max(cov) if cov else None,
                      "sr_fits": panel.get("sr_fits"),
                      "dropped": sorted(t for t, c in cov.items() if c.get("obs12m") is not None and c["obs12m"] < 0.5 * c["n"])},
            "universe": UNIVERSE}


def _pooled_rho(pr: list[dict], years: tuple[int, int]) -> float | None:
    per = defaultdict(list)
    for r in pr:
        if r["y"] is not None and years[0] <= r["year"] <= years[1]:
            per[r["year"]].append(r)
    if not per:
        return None
    return r3(float(np.mean([spearman([r["pred"] for r in v], [r["y"] for r in v]) for v in per.values()])))


def _drop_one(panel: dict, h: str, k: float, lam: float, tour: str, full: list[dict]) -> list[list]:
    """[[feature, mean yearly Spearman on the test years without it, minus the full model's]] (negative = the
    feature helps)."""
    ref = _pooled_rho(full, TEST_YEARS)
    out = []
    groups = [("age", ["age", "age2", "age_na"])] + [(f, [f]) for f in FKEYS if f not in ("age", "age2", "age_na")]
    for name, drop in groups:
        cols = [f for f in FKEYS if f not in drop]
        pr = walk_forward(panel, h, k, lam, cols, None, tour)
        v = _pooled_rho(pr, TEST_YEARS)
        out.append([name, None if (v is None or ref is None) else round(v - ref, 4)])
    return out


def _recent_lists(pr: list[dict], n_snap: int = 4) -> list[dict]:
    """The last few scored snapshots' top risers with what happened (a sanity check readers can follow)."""
    by_t: dict[str, list] = defaultdict(list)
    for r in pr:
        by_t[r["t"]].append(r)
    out = []
    for t in sorted(by_t)[-n_snap:]:
        lst = [r for r in by_t[t] if r["rank"] > 10]
        top = sorted(lst, key=lambda r: -r["p_rise"])[:TOP_N]
        bot = sorted(by_t[t], key=lambda r: -r["p_fall"])[:TOP_N]
        out.append({"t": t, "risers": [[r["pid"], int(r["rank"]), r3(r["pred"]), None if r["y"] is None else int(round(r["rank"] * math.exp(r["y"])))]
                                       for r in top],
                    "fallers": [[r["pid"], int(r["rank"]), r3(r["pred"]), None if r["y"] is None else int(round(r["rank"] * math.exp(r["y"])))]
                                for r in bot]})
    return out


def final_model(panel: dict, h: str, k: float, lam: float, asof: date) -> dict:
    """The model the live list uses: fitted on every usable row whose window closed before `asof`; plus the breakout
    and regression logistic layers and the residual quantiles by rank band (the likely range)."""
    rows = [r for r in panel["rows"] if _usable(r, h, panel["coverage"])]
    X = design(rows, h, k)
    y = np.array([r[f"y{h}"] if r[f"y{h}"] is not None else np.nan for r in rows], float)
    ye = np.array([r[f"e{h}"] if r.get(f"e{h}") is not None else np.nan for r in rows], float)
    ok = np.isfinite(y)
    if ok.sum() < 150:
        return {}
    m = Ridge(lam).fit(X[ok], y[ok])
    me = Ridge(lam).fit(X[np.isfinite(ye)], ye[np.isfinite(ye)]) if np.isfinite(ye).sum() >= 150 else None
    pred_all = m.predict(X)
    rk = np.array([r["rank"] for r in rows], float)
    rise, fall = _events(y, rk)
    sc = _prob_scale(pred_all, rk)
    Zr, Zf = _prob_z(pred_all, rk, sc)
    res = y[ok] - pred_all[ok]
    bands = {}
    for name, a, b in (("1-20", 1, 20), ("21-50", 21, 50), ("51-100", 51, 100), ("101-150", 101, 150)):
        sel = (rk[ok] >= a) & (rk[ok] <= b)
        if sel.sum() >= 30:
            bands[name] = [r3(q) for q in np.percentile(res[sel], [10, 25, 50, 75, 90])]
    return {"mu": m.mu.tolist(), "sd": m.sd.tolist(), "b0": m.b0, "b": m.b.tolist(), "keys": FKEYS, "k_shrink": k, "lam": lam,
            "elo": None if me is None else {"mu": me.mu.tolist(), "sd": me.sd.tolist(), "b0": me.b0, "b": me.b.tolist()},
            "prob_scale": sc, "b_rise": logistic(Zr, rise.astype(float)).tolist(),
            "b_fall": logistic(Zf, fall.astype(float)).tolist(), "resid": bands, "n": int(ok.sum()),
            "base_rise": r3(float(np.mean(rise[rk > 10]))), "base_fall": r3(float(np.mean(fall)))}


def _ridge_from(d: dict) -> Ridge:
    m = Ridge(d.get("lam", 10.0))
    m.mu, m.sd, m.b0, m.b = np.array(d["mu"]), np.array(d["sd"]), float(d["b0"]), np.array(d["b"])
    return m


# ---------------------------------------------------------------------------------------------- the live payloads

def _official(td: an.TourData) -> dict[str, tuple[float, float | None]]:
    """{pid: (rank, points)} from the current year's official snapshot (store "rankings")."""
    rk = td.store(td.current).get("rankings") or {}
    out = {}
    for r in rk.get("rows") or []:
        try:
            out[str(r[1])] = (float(r[0]), an.fnum(r[2]) if len(r) > 2 else None)
        except (TypeError, ValueError, IndexError):
            continue
    return out


def earn_bins(panel_rows: list[dict] | None, h: str) -> list[list[float]]:
    """Mean tour-level points earned over the horizon by the rank the model implied at the snapshot, in bands:
    [[upper implied rank, mean points, n]] (the "expected points at his level" of the points calendar)."""
    rows = [r for r in panel_rows or () if r.get(f"earn{h}") is not None and r.get("imp")]
    if len(rows) < 100:
        return []
    edges = [1, 2, 3, 5, 8, 12, 16, 20, 25, 30, 40, 50, 65, 80, 100, 125, 150, 10000]
    out = []
    lo = 0
    for hi in edges:
        sel = [r[f"earn{h}"] for r in rows if lo < r["imp"] <= hi]
        if len(sel) >= 10:
            out.append([hi, round(float(np.mean(sel)), 1), len(sel)])
        lo = hi
    return out


def bin_value(bins: list, x: float | None) -> float | None:
    if not bins or x is None:
        return None
    for hi, v, _ in bins:
        if x <= hi:
            return v
    return bins[-1][1]


def reasons(contrib: dict[str, float]) -> list[list]:
    """[[key, contribution]] grouped for reading (the age terms as one), largest first, |c| >= 0.02 (log-rank units:
    negative = towards a better rank)."""
    g = dict(contrib)
    g["age"] = g.get("age", 0.0) + g.pop("age2", 0.0) + g.pop("age_na", 0.0)
    items = sorted(((k, v) for k, v in g.items() if abs(v) >= 0.02), key=lambda kv: -abs(kv[1]))
    return [[k, round(v, 3)] for k, v in items[:6]]


def _r(x, nd=2):
    return r3(x, nd)


def build_value(td: an.TourData, entries: dict | None = None, preds: dict | None = None, today: date | None = None,
                T: dict | None = None, use_cache: bool = True) -> tuple[dict, dict]:
    """(data/<T>/value.json, data/<T>/value_validation.json). `entries` = the catalogue's season entries per year
    (players.season_entries; the luck evidence and the chain-based clutch luck need them), `preds` = the build's
    pre-match predictions by match id (the market-v-model view)."""
    from oddsmarkets.tennis.models import _io
    today = today or td.today
    C = Ctx(td, T)
    asof = quarter_start(today)
    key = history_key(td, asof)
    H = _io.cached("ace_value", f"{td.tour}_history", key, lambda: history(C, entries, asof), use_cache)
    t = today + timedelta(days=1)
    d = t.toordinal()
    off = _official(td)
    ranks: dict[str, tuple[float, float]] = {}
    for p, (rk, pts) in off.items():
        if rk <= UNIVERSE:
            ranks[p] = (rk, pts if pts is not None else float("nan"))
    if len(ranks) < 20:                       # no official snapshot (tests, a fresh store): the latest match-row ranks
        for p in C.rs:
            rb = rank_before(C.rs, p, d)
            if rb is not None and rb[0] <= UNIVERSE and p not in ranks:
                ranks[p] = (rb[0], rb[1])
    days = [(t - timedelta(days=365)).toordinal(), (t - timedelta(days=182)).toordinal(), d]
    est = elo_states(td.elo, days)
    E_now, E_6m = est[2], est[1]
    G_now = gelo_states(td.gelo, [d])[0]
    sr = sr_summary(td.season_sr(td.current))
    beta = H.get("beta") or (sr_beta(sr["mu"]) if sr else 2.0)
    feats = features_at(C, t, ranks, E_now, G_now, sr, E_6m, beta)
    pids = list(feats)
    rows = [feats[p] for p in pids]
    models = H.get("models") or {}
    preds_h = {}
    for h in HORIZONS:
        md = models.get(h) or {}
        if not md or not rows:
            continue
        X = design(rows, h, float(md.get("k_shrink", 10.0)))
        m = _ridge_from(md)
        y = m.predict(X)
        cb = m.contrib(X)
        Zr, Zf = _prob_z(y, np.array([r["rank"] for r in rows], float), md["prob_scale"])
        pr = logistic_p(np.array(md["b_rise"]), Zr)
        pf = logistic_p(np.array(md["b_fall"]), Zf)
        pe = _ridge_from(md["elo"]).predict(X) if md.get("elo") else np.full(len(rows), np.nan)
        preds_h[h] = (y, cb, pr, pf, pe)
    ebins = H.get("earn_bins") or {}
    breakout = []
    for i, p in enumerate(pids):
        r = feats[p]
        row = {"pid": p, "rank": int(r["rank"]), "pts": _r(r["pts"], 0), "age": _r(r["age"], 1), "imp": _r(r["imp"], 0),
               "n12": r["n12"], "tl12": r["tl12"], "idle": r["idle"], "d_elo": _r(r["d_elo"] * 100, 0), "d_rank": _r(r["d_rank"], 3),
               "held": _r(r["held"], 0), "drop6m": _r(r["drop6"], 0), "drop12m": _r(r["drop12"], 0),
               "luck": _r(r["luck"] * r["tl12"], 2), "draw": _r(r["draw"] * r["tl12"], 2), "mk": _r(r["mk"] * 100, 0)}
        for h, (y, cb, pr, pf, pe) in preds_h.items():
            md = models[h]
            band = "1-20" if r["rank"] <= 20 else "21-50" if r["rank"] <= 50 else "51-100" if r["rank"] <= 100 else "101-150"
            q = (md.get("resid") or {}).get(band)
            rk_pred = r["rank"] * math.exp(float(y[i]))
            row[f"y{h}"] = _r(y[i], 3)
            row[f"r{h}"] = _r(max(1.0, rk_pred), 0)
            if q:
                row[f"lo{h}"] = _r(max(1.0, rk_pred * math.exp(q[0])), 0)
                row[f"hi{h}"] = _r(rk_pred * math.exp(q[4]), 0)
            row[f"p_rise{h}"] = _r(pr[i], 3) if r["rank"] > 10 else None
            row[f"p_fall{h}"] = _r(pf[i], 3)
            row[f"elo{h}"] = _r(pe[i], 0)
            row[f"why{h}"] = reasons({k: float(cb[i][j]) for j, k in enumerate(FKEYS)})
            row[f"exp_earn{h}"] = bin_value(ebins.get(h) or [], r["imp"])
        breakout.append(row)
    breakout.sort(key=lambda x: (x.get("y12m") if x.get("y12m") is not None else 0.0))

    # ratings for every active player: over / undervalue and surfaces
    act = {p: e for p, e in E_now.items() if e[4] >= 10 and d - e[5] <= 365}
    R_all = ratings_for(list(act), act, G_now, sr, C.w, beta, C.elo_w, C.gelo_w)
    top_elo = sorted(act, key=lambda p: -act[p][0])[:100]
    offset = float(np.mean([act[p][0] - R_all[p] for p in top_elo])) if top_elo else 0.0
    R_s = {s: ratings_for(list(act), act, G_now, sr, C.w, beta, C.elo_w, C.gelo_w, surface=s) for s in an.SURFACES}
    mrank = {p: i + 1 for i, p in enumerate(sorted(R_all, key=lambda p: -R_all[p]))}
    erank = {p: i + 1 for i, p in enumerate(sorted(act, key=lambda p: -act[p][0]))}
    grank = {p: i + 1 for i, p in enumerate(sorted(act, key=lambda p: -(G_now.get(p) or (0.0,))[0]))}
    srp = (sr or {}).get("players") or {}
    srank = {p: i + 1 for i, p in enumerate(sorted([p for p in act if (srp.get(p) or [None])[0] is not None],
                                                   key=lambda p: -srp[p][0]))}
    s_rank = {s: {p: i + 1 for i, p in enumerate(sorted(R_s[s], key=lambda p: -R_s[s][p]))} for s in an.SURFACES}
    allrk = {p: v[0] for p, v in off.items()}
    for p in act:
        if p not in allrk:
            rb = rank_before(C.rs, p, d)
            if rb is not None:
                allrk[p] = rb[0]
    # the mapping uses players ranked inside MAP_RANKS: further down, ranks on match rows are sparse and stale
    imp_all = implied_ranks({p: v for p, v in allrk.items() if p in R_all and v <= MAP_RANKS}, R_all)
    pts_at = {int(v[0]): v[1] for v in off.values() if v[1] is not None}
    surf_n = _surface_counts(C.T, d - 3 * 365, d)
    value_rows = []
    for p in act:
        rk = allrk.get(p)
        if not ((rk is not None and rk <= 200) or mrank[p] <= 120):
            continue
        im = imp_all.get(p)
        value_rows.append({
            "pid": p, "rank": int(rk) if rk is not None else None, "pts": _r(off[p][1], 0) if p in off else None,
            "R": _r(R_all[p] + offset, 0), "mrank": mrank[p], "imp": int(im) if im is not None else None,
            "gap": _r(math.log(rk) - math.log(im), 3) if (rk and im) else None,
            "pts_imp": _r(pts_at.get(int(im)), 0) if im is not None else None,
            "elo": _r(act[p][0], 0), "elo_rank": erank.get(p), "g_rank": grank.get(p), "sr_rank": srank.get(p),
            "age": _r(an.age_at(C.dob.get(p), t, C.dob_from.get(p)), 1),
            "surf": {s: [_r(R_s[s][p] + offset, 0), s_rank[s].get(p), int((surf_n.get(p) or {}).get(s, 0))]
                     for s in an.SURFACES if p in R_s[s]}})
    value_rows.sort(key=lambda x: x["mrank"])

    # luck: the last 52 weeks and the current season
    clutch = chain_clutch({y: entries[y] for y in (td.current, td.current - 1) if entries and y in entries})
    wins = {"52w": ((t - timedelta(days=365)).toordinal(), d), "season": (date(td.current, 1, 1).toordinal(), d)}
    luck_rows = []
    for p, ix in C.T["by"].items():
        if not (C.T["d"][ix] >= wins["52w"][0]).any():
            continue
        rec = {}
        for wname, (lo, hi) in wins.items():
            lw = luck_window(C.T, C.L, ix, lo, hi, clutch.get(p))
            if lw["n"] >= MIN_LUCK:
                rec[wname] = _round_luck(lw)
        if rec:
            luck_rows.append({"pid": p, **rec})
    for wname in wins:
        vals = [r[wname]["sos"] for r in luck_rows if wname in r and r[wname].get("sos") is not None]
        mu = float(np.mean(vals)) if vals else 0.0
        for r in luck_rows:
            if wname in r and r[wname].get("sos") is not None:
                r[wname]["sos"] = _r(r[wname]["sos"] - mu, 1)
    luck_rows.sort(key=lambda x: -((x.get("52w") or {}).get("total") or 0.0))

    market = market_view(C, preds or {}, wins["52w"][0], d, td.tour)
    v = H.get("validation") or {}
    summ = {h: {k: ((v.get(h) or {}).get("pooled") or {}).get("test", {}).get(k)
                for k in ("rho", "rho_rank_only", "rho_rank_model", "rho_elo", "risers", "fallers", "n_obs", "years")}
            for h in HORIZONS}
    payload = {"ok": True, "tour": td.tour, "updated_at": an.now(), "as_of": today.isoformat(), "version": VERSION,
               "universe": UNIVERSE, "model_asof": H.get("asof"),
               "breakout": {"rows": breakout, "base_rise": {h: (models.get(h) or {}).get("base_rise") for h in models},
                            "base_fall": {h: (models.get(h) or {}).get("base_fall") for h in models},
                            "features": [{"key": k, "label": lab, "desc": ds} for k, lab, ds in FEATURES], "test": summ,
                            "rise_def": {"log": RISE, "places": RISE_PLACES}, "fall_def": FALL},
               "luck": {"rows": luck_rows, "params": {k: _r(x, 4) for k, x in C.lp.items()}, "min_matches": MIN_LUCK,
                        "windows": {k: [date.fromordinal(a).isoformat(), date.fromordinal(b - 1).isoformat()] for k, (a, b) in wins.items()}},
               "value": {"rows": value_rows, "offset": _r(offset, 1), "beta": _r(beta, 3), "weights": C.w},
               "market": market}
    # names for every player listed (core.js learns "names" from any payload: some ranked players have no tour-level match
    # in players_index.json)
    pids_all = {r["pid"] for r in breakout} | {r["pid"] for r in luck_rows} | {r["pid"] for r in value_rows} | {r["pid"] for r in market["rows"]}
    payload["names"] = {p: td.name(p) for p in sorted(pids_all) if td.name(p) != p}
    return payload, validation_payload(td, H)


def _round_luck(lw: dict) -> dict:
    out = {}
    for k, v in lw.items():
        if isinstance(v, dict):
            out[k] = {kk: (_r(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()}
        elif isinstance(v, float):
            out[k] = _r(v, 3 if (k.endswith("pct") or k.endswith("share")) else 2)
        else:
            out[k] = v
    return out


def _surface_counts(T: dict, lo: int, hi: int) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    sel = (T["d"] >= lo) & (T["d"] < hi) & (T["st"] != 3)
    for p, s in zip(T["pid"][sel], T["surf"][sel]):
        c = out.setdefault(p, {})
        c[s] = c.get(s, 0) + 1
    return out


def _kalshi_build(tour: str) -> dict:
    from oddsmarkets.tennis.research import kalshi_edge as KE
    df = KE.load(tour)
    if df is None or not len(df):
        return {}
    df = df[df["decision"] == "late"]
    return {str(r.id): [str(r.x_pid), round(0.5 * (float(r.bid) + float(r.ask)), 4)] for r in df.itertuples()}


def kalshi_quotes(tour: str) -> dict[str, list]:
    """{match id: [x_pid, mid price]} of the research cache's Kalshi quotes about 4 h before the start ("late"), or {}
    when the cache is absent (docs/research/tennis_edge.md, section 5; June 2025 - 1 October 2026)."""
    from oddsmarkets.tennis.models import _io
    try:
        from oddsmarkets.tennis.research.kalshi_hist import CACHE
    except Exception:  # noqa: BLE001
        return {}
    series = {"atp": "KXATPMATCH", "wta": "KXWTAMATCH"}[tour]
    idx = CACHE / f"index_{series}.json"
    if not idx.exists():
        return {}
    st = idx.stat()
    key = an.digest(VERSION, tour, st.st_size, st.st_mtime_ns)
    try:
        return _io.cached("ace_value", f"{tour}_kalshi", key, lambda: _kalshi_build(tour)) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s Kalshi quotes unavailable: %s", tour, exc)
        return {}


def market_view(C: Ctx, preds: dict, lo: int, hi: int, tour: str) -> dict:
    """Per player over [lo, hi): the model's pre-match price against the de-vigged close and Kalshi's quote before the
    start, on tour-level matches with both; and the scoreboard (log-loss) over the same matches."""
    T = C.T
    kal = kalshi_quotes(tour)
    sel = np.nonzero(T["tl"] & (T["st"] != 3) & (T["d"] >= lo) & (T["d"] < hi))[0]
    per: dict[str, dict] = {}
    tot = {"n": 0, "llm": 0.0, "llk": 0.0, "kn": 0, "kllm": 0.0, "kllk": 0.0}
    srcs: dict[str, int] = {}
    f5 = float(T.get("f5", 1.0))
    seen_b, seen_k = set(), set()
    for i in sel:
        mid = T["mid"][i]
        pr = preds.get(mid)
        if not pr or pr.get("p1_win") is None:
            continue
        me = T["pid"][i]
        pm = float(pr["p1_win"]) if T["side"][i] == 0 else 1.0 - float(pr["p1_win"])
        y = int(T["won"][i])
        f = f5 if T["bo"][i] == 5 else 1.0
        a = per.setdefault(me, {"n": 0, "w": 0, "m": 0.0, "k": 0.0, "gap": 0.0, "llm": 0.0, "llk": 0.0,
                                "kn": 0, "kw": 0, "km": 0.0, "kk": 0.0, "kgap": 0.0})
        llm = -math.log(max(1e-4, pm if y else 1 - pm))
        bk = T["book"][i]
        if bk == bk:
            llk = -math.log(max(1e-4, bk if y else 1 - bk))
            a["n"] += 1
            a["w"] += y
            a["m"] += pm
            a["k"] += bk
            a["gap"] += float((_logit(bk) - _logit(pm)) * K_ELO / f)
            a["llm"] += llm
            a["llk"] += llk
            if mid not in seen_b:
                seen_b.add(mid)
                tot["n"] += 1
                tot["llm"] += llm
                tot["llk"] += llk
                srcs[T["bsrc"][i]] = srcs.get(T["bsrc"][i], 0) + 1
        kq = kal.get(mid)
        if kq:
            pk = kq[1] if kq[0] == me else 1.0 - kq[1]
            a["kn"] += 1
            a["kw"] += y
            a["km"] += pm
            a["kk"] += pk
            a["kgap"] += float((_logit(pk) - _logit(pm)) * K_ELO / f)
            if mid not in seen_k:
                seen_k.add(mid)
                tot["kn"] += 1
                tot["kllm"] += llm
                tot["kllk"] += -math.log(max(1e-4, pk if y else 1 - pk))
    rows = []
    for p, a in per.items():
        if a["n"] < 5 and a["kn"] < 5:
            continue
        n, kn = a["n"], a["kn"]
        rows.append({"pid": p, "n": n, "w": a["w"], "x_model": _r(a["m"], 2), "x_market": _r(a["k"], 2),
                     "model": _r(a["m"] / n, 3) if n else None, "market": _r(a["k"] / n, 3) if n else None,
                     "gap": _r(a["gap"] / n, 0) if n else None,
                     "ll_model": _r(a["llm"] / n, 4) if n else None, "ll_market": _r(a["llk"] / n, 4) if n else None,
                     "k_n": kn, "k_w": a["kw"], "k_gap": _r(a["kgap"] / kn, 0) if kn else None,
                     "k_model": _r(a["km"] / kn, 3) if kn else None, "k_market": _r(a["kk"] / kn, 3) if kn else None})
    rows.sort(key=lambda x: -(abs(x["gap"]) if x.get("gap") is not None else 0))
    summary = {"n": tot["n"], "ll_model": _r(tot["llm"] / tot["n"], 4) if tot["n"] else None,
               "ll_market": _r(tot["llk"] / tot["n"], 4) if tot["n"] else None, "sources": srcs,
               "kalshi_n": tot["kn"], "kalshi_ll_model": _r(tot["kllm"] / tot["kn"], 4) if tot["kn"] else None,
               "kalshi_ll_market": _r(tot["kllk"] / tot["kn"], 4) if tot["kn"] else None, "kalshi_cache": bool(kal)}
    return {"rows": rows, "summary": summary, "window": [date.fromordinal(lo).isoformat(), date.fromordinal(hi - 1).isoformat()]}


def validation_payload(td: an.TourData, H: dict) -> dict:
    """data/<T>/value_validation.json: the walk-forward scores, baselines, tuning grid, coefficients, the age curve and
    the luck evidence (everything the Validation view and the Methodology quote)."""
    coefs = {}
    for h, md in (H.get("models") or {}).items():
        if not md:
            continue
        keys = md.get("keys") or FKEYS
        coefs[h] = {"rank": [[k, _r(b, 4)] for k, b in zip(keys, md.get("b") or [])],
                    "elo": [[k, _r(b, 4)] for k, b in zip(keys, ((md.get("elo") or {}).get("b") or []))],
                    "n": md.get("n"), "resid": md.get("resid"), "base_rise": md.get("base_rise"), "base_fall": md.get("base_fall")}
    pids = {x[0] for v in (H.get("validation") or {}).values() for s in (v.get("recent") or []) for k in ("risers", "fallers")
            for x in s.get(k) or []}
    return {"ok": True, "tour": td.tour, "updated_at": an.now(), "version": VERSION, "asof": H.get("asof"),
            "names": {p: td.name(p) for p in sorted(pids) if td.name(p) != p},
            "tuned": H.get("tuned"), "validation": H.get("validation"), "coefficients": coefs, "age_curve": H.get("age_curve"),
            "luck_evidence": H.get("luck_evidence"), "luck_params": H.get("luck_params"), "panel": H.get("panel"),
            "drop_one": H.get("drop_one"), "earn_bins": H.get("earn_bins"),
            "features": [{"key": k, "label": lab, "desc": ds} for k, lab, ds in FEATURES],
            "definitions": {"universe": UNIVERSE, "rank_before_days": RANK_BEFORE, "target_window_days": RANK_AROUND,
                            "rise": {"log": RISE, "places": RISE_PLACES}, "fall_log": FALL, "top_n": TOP_N,
                            "dev_years": list(DEV_YEARS), "test_years": list(TEST_YEARS), "horizons": HORIZONS,
                            "first_snapshot": FIRST_SNAP.get(td.tour), "snap_months": list(SNAP_MONTHS)}}
