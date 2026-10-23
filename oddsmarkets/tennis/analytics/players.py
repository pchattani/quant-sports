"""
Player catalogue (data/<T>/<year>/players.json, 138 metrics) and career files (data/<T>/players/<pid>.json).

Per season, every tour-level main-draw match that was played (done / ret / def; walkovers excluded) gives
each player an entry with the result, sets from her side, the opponent's rank and Elo, the WTA stats when
present, and the model expectations used by the "against expectation" metrics:

* Elo expectation: B's walk-forward pre-match Elo probability (`elo.pre_match`), so "wins over expected"
  and upsets use only information from before each match.
* Chain expectations (clutch): each match's serve-point probabilities from B's serve/return model fitted
  through the season's end (in-season; the same fit for every match of the season), priced through C's
  exact chain: a tiebreak's P(win) (first server averaged; to 10 in a deciding-set match tiebreak), a
  deciding set's P(win) under its rule, and P(win the match | lost the first set) from the LiveTable.
* Real-stats expectation (WTA): the model's calibrated hold and serve-points-won against that opponent
  (k_hold and k_spw offsets), summed over the service games / points actually played.

Percentiles: 100 = best, reversed where lower is better, against the season's qualified players (a
matches floor that scales with how much of the season has been played); rates with a sample size are
shrunk towards the pool mean by a few pseudo-matches before placing (values are shown unshrunk). The
surface view places each player's surface values among players with enough matches on that surface.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np

from oddsmarkets.tennis import analytics as an
from oddsmarkets.tennis.analytics import metric

logger = logging.getLogger(__name__)
VERSION = 1

M = metric
METRICS: list[dict] = [
    # results
    M("matches", "Matches", "Results", "int", desc="Tour-level main-draw matches played (walkovers excluded)."),
    M("wins", "Wins", "Results", "int"),
    M("losses", "Losses", "Results", "int", lower=True),
    M("win_pct", "Win %", "Results", "pct"),
    M("win_slam", "Win % at Slams", "Results", "pct"),
    M("win_m1000", "Win % at Masters / 1000s", "Results", "pct"),
    M("win_500", "Win % at 500s", "Results", "pct"),
    M("win_250", "Win % at 250s", "Results", "pct"),
    M("win_v_top10", "Win % v top 10", "Results", "pct"),
    M("wins_top10", "Wins v top 10", "Results", "int"),
    M("win_v_top20", "Win % v top 20", "Results", "pct"),
    M("win_v_top50", "Win % v top 50", "Results", "pct"),
    M("titles", "Titles", "Results", "int"),
    M("finals", "Finals", "Results", "int"),
    M("final_win_pct", "Finals won %", "Results", "pct"),
    M("slam_wins", "Slam match wins", "Results", "int"),
    M("upsets", "Upset wins", "Results", "int"),
    M("upset_losses", "Upset losses", "Results", "int", lower=True),
    M("wins_over_exp", "Wins over expected", "Results", "signed"),
    M("woe_pm", "Wins over expected per match", "Results", "3"),
    M("avg_opp_elo", "Average opponent Elo", "Results", "1"),
    M("win_hard", "Win % on hard", "Results", "pct"),
    M("win_clay", "Win % on clay", "Results", "pct"),
    M("win_grass", "Win % on grass", "Results", "pct"),
    M("win_indoor", "Win % indoors", "Results", "pct"),
    # serve, inferred
    M("hold", "Hold %", "Serve (inferred)", "pct"),
    M("serve_rating", "Serve rating", "Serve (inferred)", "2"),
    M("spw_exp", "Serve points won % (model)", "Serve (inferred)", "pct"),
    M("serve_se", "Serve rating s.e.", "Serve (inferred)", "2", lower=True),
    M("hold_hard", "Hold % on hard", "Serve (inferred)", "pct"),
    M("hold_clay", "Hold % on clay", "Serve (inferred)", "pct"),
    M("hold_grass", "Hold % on grass", "Serve (inferred)", "pct"),
    M("hold_v_strong", "Hold % v strong returners", "Serve (inferred)", "pct"),
    # return, inferred
    M("brk", "Break %", "Return (inferred)", "pct"),
    M("return_rating", "Return rating", "Return (inferred)", "2"),
    M("rpw_exp", "Return points won % (model)", "Return (inferred)", "pct"),
    M("return_se", "Return rating s.e.", "Return (inferred)", "2", lower=True),
    M("brk_hard", "Break % on hard", "Return (inferred)", "pct"),
    M("brk_clay", "Break % on clay", "Return (inferred)", "pct"),
    M("brk_grass", "Break % on grass", "Return (inferred)", "pct"),
    M("brk_v_strong", "Break % v strong servers", "Return (inferred)", "pct"),
    M("sr_total", "Serve + return rating", "Return (inferred)", "2"),
    M("hold_plus_break", "Hold % + break %", "Return (inferred)", "pct"),
    # real stats (WTA API)
    M("stats_matches", "Matches with stats", "Serve (WTA stats)", "int", scope="wta_stats"),
    M("ace_pct", "Ace %", "Serve (WTA stats)", "pct", scope="wta_stats"),
    M("df_pct", "Double-fault %", "Serve (WTA stats)", "pct", lower=True, scope="wta_stats"),
    M("first_in", "1st serve in %", "Serve (WTA stats)", "pct", scope="wta_stats"),
    M("first_won", "1st serve points won %", "Serve (WTA stats)", "pct", scope="wta_stats"),
    M("second_won", "2nd serve points won %", "Serve (WTA stats)", "pct", scope="wta_stats"),
    M("spw_real", "Serve points won %", "Serve (WTA stats)", "pct", scope="wta_stats"),
    M("hold_real", "Hold % (actual)", "Serve (WTA stats)", "pct", scope="wta_stats"),
    M("bp_saved_pct", "Break points saved %", "Serve (WTA stats)", "pct", scope="wta_stats"),
    M("bp_faced_pg", "Break points faced per service game", "Serve (WTA stats)", "3", lower=True, scope="wta_stats"),
    M("aces_pm", "Aces per match", "Serve (WTA stats)", "2", scope="wta_stats"),
    M("dfs_pm", "Double faults per match", "Serve (WTA stats)", "2", lower=True, scope="wta_stats"),
    M("spw_vs_exp", "Serve points won v expected", "Serve (WTA stats)", "signed", scope="wta_stats"),
    M("hold_vs_exp", "Hold % v expected", "Serve (WTA stats)", "signed", scope="wta_stats"),
    M("rpw_real", "Return points won %", "Return (WTA stats)", "pct", scope="wta_stats"),
    M("brk_real", "Break % (actual)", "Return (WTA stats)", "pct", scope="wta_stats"),
    M("bp_conv_pct", "Break points converted %", "Return (WTA stats)", "pct", scope="wta_stats"),
    M("bp_opps_pg", "Break points per return game", "Return (WTA stats)", "3", scope="wta_stats"),
    M("tpw", "Total points won %", "Return (WTA stats)", "pct", scope="wta_stats"),
    M("dominance", "Dominance ratio", "Return (WTA stats)", "2", scope="wta_stats"),
    M("rpw_vs_exp", "Return points won v expected", "Return (WTA stats)", "signed", scope="wta_stats"),
    M("brk_vs_exp", "Break % v expected", "Return (WTA stats)", "signed", scope="wta_stats"),
    # clutch
    M("tb_w", "Tiebreaks won", "Clutch", "int"),
    M("tb_l", "Tiebreaks lost", "Clutch", "int", lower=True),
    M("tb_pct", "Tiebreak win %", "Clutch", "pct"),
    M("tb_exp", "Tiebreak win % expected", "Clutch", "pct"),
    M("tb_over", "Tiebreaks won over expected", "Clutch", "signed"),
    M("dec_w", "Deciding sets won", "Clutch", "int"),
    M("dec_l", "Deciding sets lost", "Clutch", "int", lower=True),
    M("dec_pct", "Deciding-set win %", "Clutch", "pct"),
    M("dec_over", "Deciding sets won over expected", "Clutch", "signed"),
    M("fsd_w", "Wins from a set down", "Clutch", "int"),
    M("fsd_pct", "Win % after losing the first set", "Clutch", "pct"),
    M("fsd_over", "Comebacks over expected", "Clutch", "signed"),
    M("blown", "Losses after winning the first set", "Clutch", "int", lower=True),
    M("bagels_for", "Bagels (6-0 sets won)", "Clutch", "int"),
    M("bagels_against", "Bagels conceded", "Clutch", "int", lower=True),
    M("breadsticks_for", "Breadsticks (6-1 sets won)", "Clutch", "int"),
    M("breadsticks_against", "Breadsticks conceded", "Clutch", "int", lower=True),
    M("close_sets_pct", "Close sets won %", "Clutch", "pct"),
    # efficiency and length
    M("games_won_pct", "Games won %", "Efficiency", "pct"),
    M("sets_won_pct", "Sets won %", "Efficiency", "pct"),
    M("games_per_set", "Games per set", "Efficiency", "2"),
    M("games_per_match", "Games per match", "Efficiency", "1"),
    M("straight_win_pct", "Wins in straight sets %", "Efficiency", "pct"),
    M("straight_loss_pct", "Losses in straight sets %", "Efficiency", "pct", lower=True),
    M("avg_margin", "Game margin per match", "Efficiency", "signed"),
    M("win_games_pct", "Games won % in wins", "Efficiency", "pct"),
    M("close_out", "Win % after winning the first set", "Efficiency", "pct"),
    M("tb_per_set", "Tiebreaks per set", "Efficiency", "3"),
    M("duration_avg", "Match length (min)", "Efficiency", "int"),
    M("ret_losses", "Retirements", "Efficiency", "int", lower=True),
    # form
    M("elo", "Elo", "Form", "1"),
    M("elo_hard", "Hard Elo", "Form", "1"),
    M("elo_clay", "Clay Elo", "Form", "1"),
    M("elo_grass", "Grass Elo", "Form", "1"),
    M("elo_rank", "Elo rank", "Form", "int", lower=True),
    M("elo_peak", "Peak Elo in the season", "Form", "1"),
    M("elo_d30", "Elo change, 30 days", "Form", "signed"),
    M("elo_d90", "Elo change, 90 days", "Form", "signed"),
    M("elo_d365", "Elo change, 365 days", "Form", "signed"),
    M("hot_hand", "Hot hand (last 10)", "Form", "3"),
    M("best_streak", "Longest win streak", "Form", "int"),
    # style (Match Charting Project, career profile)
    M("ch_matches", "Charted matches", "Style", "int", scope="charted"),
    M("wide_deuce", "1st serve wide, deuce", "Style", "pct", scope="charted"),
    M("t_deuce", "1st serve T, deuce", "Style", "pct", scope="charted"),
    M("body_deuce", "1st serve body, deuce", "Style", "pct", scope="charted"),
    M("wide_ad", "1st serve wide, ad", "Style", "pct", scope="charted"),
    M("t_ad", "1st serve T, ad", "Style", "pct", scope="charted"),
    M("body_ad", "1st serve body, ad", "Style", "pct", scope="charted"),
    M("unret_rate", "Unreturned serves %", "Style", "pct", scope="charted"),
    M("snv_rate", "Serve and volley %", "Style", "pct", scope="charted"),
    M("rally_len", "Average rally length", "Style", "2", scope="charted"),
    M("rally_short", "Rallies of 1-3 shots %", "Style", "pct", scope="charted"),
    M("rally_long", "Rallies of 10+ shots %", "Style", "pct", scope="charted"),
    M("won_long", "Long rallies won %", "Style", "pct", scope="charted"),
    M("won_short", "Short rallies won %", "Style", "pct", scope="charted"),
    M("winners_pp", "Winners per point", "Style", "3", scope="charted"),
    M("ue_pp", "Unforced errors per point", "Style", "3", lower=True, scope="charted"),
    M("w_ue_ratio", "Winners / unforced errors", "Style", "2", scope="charted"),
    M("fh_share", "Forehand share", "Style", "pct", scope="charted"),
    M("fh_winners_pp", "Forehand winners per point", "Style", "3", scope="charted"),
    M("bh_winners_pp", "Backhand winners per point", "Style", "3", scope="charted"),
    M("net_rate", "Net approaches per point", "Style", "pct", scope="charted"),
    M("net_won", "Net points won %", "Style", "pct", scope="charted"),
    M("ret_deep", "Deep returns %", "Style", "pct", scope="charted"),
    M("aggression", "Aggression score", "Style", "3", scope="charted"),
    # ranking
    M("rank", "Rank", "Ranking", "int", lower=True, desc="Official rank (current season: the latest snapshot; past seasons: "
                                                         "the rank carried into the season's last match)."),
    M("best_rank", "Best rank in the season", "Ranking", "int", lower=True),
    M("points", "Ranking points", "Ranking", "int"),
    M("race_pts", "Race points", "Ranking", "int"),
    M("to_defend", "Points to defend", "Ranking", "int", lower=True),
    M("proj_rank", "Projected year-end rank", "Ranking", "int", lower=True),
    M("p_finals", "Finals qualification probability", "Ranking", "prob"),
    M("p_no1", "Year-end No. 1 probability", "Ranking", "prob"),
]
from oddsmarkets.tennis.analytics.glossary import DESC as _DESC  # noqa: E402

for _m in METRICS:
    _m["desc"] = _m["desc"] or _DESC.get(_m["key"], "")
METRIC_KEYS = [m["key"] for m in METRICS]
BY_KEY = {m["key"]: m for m in METRICS}
SURFACE_GROUPS = ("Results", "Serve (inferred)", "Return (inferred)", "Serve (WTA stats)", "Return (WTA stats)", "Clutch",
                  "Efficiency")
SURFACE_SKIP = {"win_hard", "win_clay", "win_grass", "win_indoor", "hold_hard", "hold_clay", "hold_grass", "brk_hard",
                "brk_clay", "brk_grass", "hold_v_strong", "brk_v_strong"}
SURFACE_KEYS = [m["key"] for m in METRICS if m["group"] in SURFACE_GROUPS and m["key"] not in SURFACE_SKIP]
# Ratings ranked in the surface pool as well (values_surface.<s> / pct_surface.<s>; not in the lab's surface block):
# elo_surface = that surface's Elo (values.elo_<s>), elo = the overall Elo, both at the season's end
# (docs/METRICS_SPEC.md, tennis surface groups).
ELO_SURFACE = M("elo_surface", "Surface Elo", "Form", "1", desc="The surface's own Elo rating (hard, clay or grass) at the season's "
                "end, ranked among the players with enough matches on that surface.")
BY_KEY["elo_surface"] = ELO_SURFACE
SURFACE_RATING_KEYS = ["elo_surface", "elo"]
# rate -> (sample-size key, pseudo-observations) for the percentile shrinkage. win_pct 20 and games_won_pct 12 follow
# the measured stabilisation (docs/METRICS_SPEC.md, tennis: M50 about 16-26 matches for win %, 12-17 for games won %);
# display only (no model reads these percentiles).
SHRINK = {"win_pct": ("matches", 20), "win_v_top10": ("n_top10", 4), "win_v_top20": ("n_top20", 5), "win_v_top50": ("n_top50", 6),
          "win_slam": ("n_slam", 5), "win_m1000": ("n_m1000", 5), "win_500": ("n_500", 5), "win_250": ("n_250", 5),
          "tb_pct": ("tb_n", 8), "dec_pct": ("dec_n", 6), "fsd_pct": ("fsd_n", 6), "close_out": ("fsu_n", 6),
          "close_sets_pct": ("close_n", 8), "final_win_pct": ("finals", 2), "straight_win_pct": ("wins", 6),
          "games_won_pct": ("matches", 12), "sets_won_pct": ("matches", 8), "woe_pm": ("matches", 10)}
SURFACE_FLOOR = {"hard": 10, "clay": 8, "grass": 5}
MIN_LIST = 5
UPSET_P = 0.4


# ---------------------------------------------------------------------------------------------- per-match entries

def _set_done(a: int, b: int, decider: bool, rule: str) -> bool:
    hi, lo = max(a, b), min(a, b)
    if decider and rule == "adv":
        return hi >= 6 and hi - lo >= 2
    if decider and rule == "tb12":
        return (hi >= 6 and hi - lo >= 2) or (hi == 13 and lo == 12)
    return (hi == 6 and lo <= 4) or (hi == 7 and lo in (5, 6))


def _is_tb(a: int, b: int, decider: bool, rule: str) -> bool:
    if decider and rule == "adv":
        return False
    if decider and rule == "tb12":
        return {a, b} == {13, 12}
    return {a, b} == {7, 6}


def season_entries(td: an.TourData, year: int, sr: dict | None = None) -> dict[str, list[dict]]:
    """{pid: [entry]} for the season's tour-level main-draw matches that were played (see the module docstring)."""
    from oddsmarkets.tennis.models import match_chain as mc
    from oddsmarkets.tennis.models import serve_return as SR
    sr = sr if sr is not None else td.season_sr(year)
    evs = td.events(year)
    ms = [m for m in td.matches(year).values() if an.is_tour_level(m) and m.get("status") in an.PLAYED
          and m.get("p1") and m.get("p2") and m.get("winner")]
    ms.sort(key=lambda m: (str(m.get("date") or (evs.get(m.get("event")) or {}).get("start") or ""), an.ROUND_ORDER.get(m.get("round"), 5)))
    n = len(ms)
    pa, pb = np.full(n, np.nan), np.full(n, np.nan)
    hc1, hc2 = np.full(n, np.nan), np.full(n, np.nan)            # calibrated holds (display scale)
    hh1, hh2 = np.full(n, np.nan), np.full(n, np.nan)            # chain-scale holds
    k_spw = float(((sr or {}).get("base") or {}).get("k_spw", 0.0)) if sr else 0.0
    if sr and sr.get("players") is not None:
        for i, m in enumerate(ms):
            try:
                args = (m.get("surface") or "hard", m.get("level"), int(m.get("best_of") or 3), bool(m.get("indoor")))
                h1 = SR.hold_prob(sr, m["p1"], m["p2"], *args)
                h2 = SR.hold_prob(sr, m["p2"], m["p1"], *args)
                pa[i], pb[i] = SR.point_prob_from_hold(h1), SR.point_prob_from_hold(h2)
                hh1[i], hh2[i] = h1, h2
                hc1[i] = SR.hold_prob(sr, m["p1"], m["p2"], *args, calibrated=True)
                hc2[i] = SR.hold_prob(sr, m["p2"], m["p1"], *args, calibrated=True)
            except Exception:  # noqa: BLE001
                pass
    ok = np.isfinite(pa) & np.isfinite(pb)
    # chain expectations, vectorised by (best of, rule)
    p01 = np.full(n, np.nan)
    p10 = np.full(n, np.nan)
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, m in enumerate(ms):
        if ok[i]:
            groups[(5 if int(m.get("best_of") or 3) == 5 else 3, an.chain_rule(m))].append(i)
    for (bo, rule), idx in groups.items():
        ix = np.array(idx)
        try:
            lt = mc.LiveTable(pa[ix], pb[ix], bo, rule)
            p01[ix] = lt.p((0, 1), (0, 0), None)
            p10[ix] = lt.p((1, 0), (0, 0), None)
        except Exception as exc:  # noqa: BLE001
            logger.debug("live table failed: %s", exc)
    tbs: list[tuple] = []                                   # (match idx, set idx, to, p1 won)
    decs: list[tuple] = []                                  # (match idx, rule, p1 won)
    meta: list[dict] = []
    for i, m in enumerate(ms):
        bo = 5 if int(m.get("best_of") or 3) == 5 else 3
        rule = an.chain_rule(m)
        sets = an.set_pairs(m)
        done_sets = []
        for k, (a, b) in enumerate(sets):
            decider = k == bo - 1
            if not _set_done(a, b, decider, rule):
                break
            done_sets.append((a, b, decider))
            if _is_tb(a, b, decider, rule):
                to = 10 if (decider and rule == "tb10") else 7
                tbs.append((i, k, to, a > b))
        if len(done_sets) == bo and m.get("status") == "done":
            decs.append((i, rule, done_sets[-1][0] > done_sets[-1][1]))
        meta.append({"sets": done_sets})
    tb_exp = {}
    if tbs:
        arr = [t for t in tbs if ok[t[0]]]
        for to in (7, 10):
            sel = [t for t in arr if t[2] == to]
            if not sel:
                continue
            ix = np.array([t[0] for t in sel])
            e = 0.5 * (np.asarray(mc.tiebreak_win(pa[ix], pb[ix], to, 0)) + np.asarray(mc.tiebreak_win(pa[ix], pb[ix], to, 1)))
            for t, v in zip(sel, np.atleast_1d(e)):
                tb_exp[(t[0], t[1])] = float(v)
    dec_exp = {}
    if decs:
        by_rule: dict[str, list] = defaultdict(list)
        for d in decs:
            if ok[d[0]]:
                by_rule[d[1]].append(d)
        for rule, sel in by_rule.items():
            ix = np.array([d[0] for d in sel])
            try:
                e = 0.5 * (np.asarray(mc.set_win(pa[ix], pb[ix], 0, rule)) + np.asarray(mc.set_win(pa[ix], pb[ix], 1, rule)))
            except Exception:  # noqa: BLE001
                continue
            for d, v in zip(sel, np.atleast_1d(e)):
                dec_exp[d[0]] = float(v)
    tb_by: dict[int, list] = defaultdict(list)
    for t in tbs:
        tb_by[t[0]].append(t)
    dec_by = {d[0]: d for d in decs}
    out: dict[str, list[dict]] = defaultdict(list)
    for i, m in enumerate(ms):
        g = td.elo_row(m["id"])
        ep = td.elo_pre(m)
        sets = meta[i]["sets"]
        st = m.get("stats") if isinstance(m.get("stats"), dict) else None
        d = an.day(m.get("date")) or an.day((evs.get(m.get("event")) or {}).get("start"))
        for side in (0, 1):
            me, op = (m["p1"], m["p2"]) if side == 0 else (m["p2"], m["p1"])
            won = str(m["winner"]) == str(me)
            mine = [(a, b) if side == 0 else (b, a) for a, b, _ in sets]
            tb_list = []
            for (ii, k, to, p1won) in tb_by.get(i, ()):
                e = tb_exp.get((i, k))
                tb_list.append((p1won if side == 0 else not p1won, None if e is None else (e if side == 0 else 1 - e)))
            dec = None
            dd = dec_by.get(i)
            if dd is not None:
                e = dec_exp.get(i)
                dec = (dd[2] if side == 0 else not dd[2], None if e is None else (e if side == 0 else 1 - e))
            first_lost = bool(mine) and mine[0][0] < mine[0][1]
            fsd = None
            if first_lost:
                # P(this player wins | down a set): p1 down 0-1 -> p01; p2 down (p1 up 1-0) -> 1 - p10
                e = p01[i] if side == 0 else (1 - p10[i] if np.isfinite(p10[i]) else np.nan)
                fsd = (won, float(e) if np.isfinite(e) else None)
            opp_elo = None
            if g is not None:
                opp_elo = an.fnum(g[10] if str(g[2]) == str(me) else g[8])
            rk_me, rk_op = (m.get("rank1"), m.get("rank2")) if side == 0 else (m.get("rank2"), m.get("rank1"))
            ent = {"mid": m["id"], "date": d, "event": m.get("event"), "level": str(m.get("level")), "round": m.get("round"),
                   "surface": m.get("surface") or "hard", "indoor": bool(m.get("indoor")), "won": won, "opp": str(op),
                   "status": m.get("status"), "bo": 5 if int(m.get("best_of") or 3) == 5 else 3, "sets": mine,
                   "tbs": tb_list, "dec": dec, "fsd": fsd, "first_won": bool(mine) and mine[0][0] > mine[0][1],
                   "elo_p": None if ep is None else (ep if side == 0 else 1 - ep), "opp_elo": opp_elo,
                   "opp_rank": an.inum(rk_op), "rank": an.inum(rk_me), "dur": an.inum(m.get("duration_min")),
                   "p_srv": (float(pa[i]), float(pb[i])) if ok[i] and side == 0 else ((float(pb[i]), float(pa[i])) if ok[i] else None)}
            if st and st.get("p1") and st.get("p2"):
                s_me, s_op = (st["p1"], st["p2"]) if side == 0 else (st["p2"], st["p1"])
                h_me, h_op = (hc1[i], hc2[i]) if side == 0 else (hc2[i], hc1[i])
                c_me, c_op = (hh1[i], hh2[i]) if side == 0 else (hh2[i], hh1[i])
                ent["stats"] = (s_me, s_op)
                if np.isfinite(h_me) and np.isfinite(h_op):
                    spw = getattr(SR, "_spw", None)
                    ent["exp"] = {"hold": float(h_me), "brk": float(1 - h_op),
                                  "spw": float(spw(c_me, k_spw)) if spw else None,
                                  "spw_op": float(spw(c_op, k_spw)) if spw else None}
            out[str(me)].append(ent)
    return out


# ---------------------------------------------------------------------------------------------- values

def _pct(w, n):
    return w / n if n else None


def titles_finals(td: an.TourData, year: int) -> dict[str, dict[str, list[int]]]:
    """{pid: {"all" | surface: [titles, finals]}} from the season's tour-level finals, walkovers included: a final won
    by a walkover is still a title and its opponent still a finalist (the entries leave walkovers out, as every rate
    should)."""
    out: dict[str, dict[str, list[int]]] = {}
    for m in td.matches(year).values():
        if (m.get("round") != "F" or not an.is_tour_level(m) or m.get("status") not in an.FINISHED or not m.get("winner")
                or not m.get("p1") or not m.get("p2")):
            continue
        for p in (str(m["p1"]), str(m["p2"])):
            for k in ("all", m.get("surface") or "hard"):
                c = out.setdefault(p, {}).setdefault(k, [0, 0])
                c[1] += 1
                c[0] += int(p == str(m["winner"]))
    return out


def _apply_titles(v: dict, nn: dict | None, tf: list[int] | None) -> None:
    """Titles / finals / final win % from `titles_finals` (walkover finals counted)."""
    t, f = tf or (0, 0)
    v.update(titles=t, finals=f, final_win_pct=_pct(t, f))
    if nn is not None:
        nn["finals"] = f


def values_from(E: list[dict], rec: dict | None) -> tuple[dict, dict]:
    """(metric values, sample sizes) from a player's entries and her serve/return record."""
    v: dict[str, Any] = {}
    nn: dict[str, float] = {}
    n = len(E)
    w = sum(1 for e in E if e["won"])
    v.update(matches=n, wins=w, losses=n - w, win_pct=_pct(w, n))
    nn.update(matches=n, wins=w)
    for lv in ("slam", "m1000", "500", "250"):
        s = [e for e in E if e["level"] == lv]
        v[f"win_{lv}"] = _pct(sum(e["won"] for e in s), len(s))
        nn[f"n_{lv}"] = len(s)
    for k in (10, 20, 50):
        s = [e for e in E if e["opp_rank"] is not None and e["opp_rank"] <= k]
        v[f"win_v_top{k}"] = _pct(sum(e["won"] for e in s), len(s))
        nn[f"n_top{k}"] = len(s)
        if k == 10:
            v["wins_top10"] = sum(e["won"] for e in s)
    fin = [e for e in E if e["round"] == "F"]
    v.update(titles=sum(e["won"] for e in fin), finals=len(fin), final_win_pct=_pct(sum(e["won"] for e in fin), len(fin)))
    nn["finals"] = len(fin)
    v["slam_wins"] = sum(1 for e in E if e["won"] and e["level"] == "slam")
    ex = [e for e in E if e["elo_p"] is not None]
    v["upsets"] = sum(1 for e in ex if e["won"] and e["elo_p"] < UPSET_P)
    v["upset_losses"] = sum(1 for e in ex if not e["won"] and e["elo_p"] > 1 - UPSET_P)
    v["wins_over_exp"] = sum(e["won"] - e["elo_p"] for e in ex) if ex else None
    v["woe_pm"] = v["wins_over_exp"] / len(ex) if ex else None
    v["avg_opp_elo"] = an.mean(e["opp_elo"] for e in E)
    for s in an.SURFACES:
        x = [e for e in E if e["surface"] == s]
        v[f"win_{s}"] = _pct(sum(e["won"] for e in x), len(x))
    x = [e for e in E if e["indoor"]]
    v["win_indoor"] = _pct(sum(e["won"] for e in x), len(x))
    # inferred serve / return
    if rec:
        v.update(hold=rec.get("hold"), serve_rating=rec.get("s"), spw_exp=rec.get("spw"), serve_se=rec.get("se_s"),
                 brk=rec.get("break"), return_rating=rec.get("r"), rpw_exp=rec.get("rpw"), return_se=rec.get("se_r"))
        if rec.get("s") is not None and rec.get("r") is not None:
            v["sr_total"] = rec["s"] + rec["r"]
        if rec.get("hold") is not None and rec.get("break") is not None:
            v["hold_plus_break"] = rec["hold"] + rec["break"]
    # real stats
    tot = defaultdict(float)
    ns = 0
    for e in E:
        st = e.get("stats")
        if not st:
            continue
        a, b = st
        need = ("sv_pts", "fs_in", "fs_won", "ss_won", "sv_gms", "bp_saved", "bp_faced")
        if any(a.get(k) is None for k in need) or any(b.get(k) is None for k in ("sv_pts", "fs_won", "ss_won", "sv_gms")):
            continue
        if not a["sv_pts"] or not b["sv_pts"]:
            continue
        ns += 1
        for k in ("aces", "dfs", "sv_pts", "fs_in", "fs_won", "ss_won", "sv_gms", "bp_saved", "bp_faced", "bp_conv", "bp_opps"):
            if a.get(k) is not None:
                tot[k] += float(a[k])
        tot["n_aces"] += 1 if a.get("aces") is not None else 0
        tot["n_dfs"] += 1 if a.get("dfs") is not None else 0
        tot["o_sv_pts"] += float(b["sv_pts"])
        tot["o_sv_won"] += float(b["fs_won"]) + float(b["ss_won"])
        tot["o_sv_gms"] += float(b["sv_gms"])
        if b.get("bp_faced") is not None and b.get("bp_saved") is not None:
            tot["o_brk"] += float(b["bp_faced"]) - float(b["bp_saved"])
            tot["o_gms_bp"] += float(b["sv_gms"])
        x = e.get("exp") or {}
        if x.get("spw") is not None:
            tot["x_spw"] += x["spw"] * float(a["sv_pts"])
            tot["x_spw_n"] += float(a["sv_pts"])
        if x.get("spw_op") is not None:
            tot["x_rpw"] += (1 - x["spw_op"]) * float(b["sv_pts"])
            tot["x_rpw_n"] += float(b["sv_pts"])
        if x.get("hold") is not None:
            tot["x_hold"] += x["hold"] * float(a["sv_gms"])
            tot["x_hold_n"] += float(a["sv_gms"])
        if x.get("brk") is not None:
            tot["x_brk"] += x["brk"] * float(b["sv_gms"])
            tot["x_brk_n"] += float(b["sv_gms"])
    if ns:
        sp = tot["sv_pts"]
        won = tot["fs_won"] + tot["ss_won"]
        v["stats_matches"] = ns
        v["ace_pct"] = _pct(tot["aces"], sp) if tot["n_aces"] else None
        v["df_pct"] = _pct(tot["dfs"], sp) if tot["n_dfs"] else None
        v["first_in"] = _pct(tot["fs_in"], sp)
        v["first_won"] = _pct(tot["fs_won"], tot["fs_in"])
        v["second_won"] = _pct(tot["ss_won"], sp - tot["fs_in"])
        v["spw_real"] = _pct(won, sp)
        v["hold_real"] = _pct(tot["sv_gms"] - (tot["bp_faced"] - tot["bp_saved"]), tot["sv_gms"])
        v["bp_saved_pct"] = _pct(tot["bp_saved"], tot["bp_faced"])
        v["bp_faced_pg"] = _pct(tot["bp_faced"], tot["sv_gms"])
        v["aces_pm"] = tot["aces"] / ns if tot["n_aces"] else None
        v["dfs_pm"] = tot["dfs"] / ns if tot["n_dfs"] else None
        rpw = _pct(tot["o_sv_pts"] - tot["o_sv_won"], tot["o_sv_pts"])
        v["rpw_real"] = rpw
        v["brk_real"] = _pct(tot["o_brk"], tot["o_gms_bp"])
        v["bp_conv_pct"] = _pct(tot["bp_conv"], tot["bp_opps"]) if tot["bp_opps"] else None
        v["bp_opps_pg"] = _pct(tot["bp_opps"], tot["o_sv_gms"]) if tot["bp_opps"] else None
        v["tpw"] = _pct(won + tot["o_sv_pts"] - tot["o_sv_won"], sp + tot["o_sv_pts"])
        if v["spw_real"] is not None and rpw is not None and v["spw_real"] < 1:
            v["dominance"] = rpw / (1 - v["spw_real"])
        if tot["x_spw_n"]:
            v["spw_vs_exp"] = v["spw_real"] - tot["x_spw"] / tot["x_spw_n"]
        if tot["x_rpw_n"] and rpw is not None:
            v["rpw_vs_exp"] = rpw - tot["x_rpw"] / tot["x_rpw_n"]
        if tot["x_hold_n"] and v["hold_real"] is not None:
            v["hold_vs_exp"] = v["hold_real"] - tot["x_hold"] / tot["x_hold_n"]
        if tot["x_brk_n"] and v["brk_real"] is not None:
            v["brk_vs_exp"] = v["brk_real"] - tot["x_brk"] / tot["x_brk_n"]
    # clutch
    tbl = [t for e in E for t in e["tbs"]]
    tw = sum(1 for t in tbl if t[0])
    v.update(tb_w=tw, tb_l=len(tbl) - tw, tb_pct=_pct(tw, len(tbl)))
    te = [t[1] for t in tbl if t[1] is not None]
    v["tb_exp"] = sum(te) / len(te) if te else None
    v["tb_over"] = (sum(1 for t in tbl if t[0] and t[1] is not None) - sum(te)) if te else None
    nn["tb_n"] = len(tbl)
    dl = [e["dec"] for e in E if e["dec"] is not None]
    dw = sum(1 for d in dl if d[0])
    v.update(dec_w=dw, dec_l=len(dl) - dw, dec_pct=_pct(dw, len(dl)))
    de = [d for d in dl if d[1] is not None]
    v["dec_over"] = (sum(1 for d in de if d[0]) - sum(d[1] for d in de)) if de else None
    nn["dec_n"] = len(dl)
    fl = [e["fsd"] for e in E if e["fsd"] is not None]
    fw = sum(1 for f in fl if f[0])
    v.update(fsd_w=fw, fsd_pct=_pct(fw, len(fl)))
    fe = [f for f in fl if f[1] is not None]
    v["fsd_over"] = (sum(1 for f in fe if f[0]) - sum(f[1] for f in fe)) if fe else None
    nn["fsd_n"] = len(fl)
    fu = [e for e in E if e["first_won"]]
    v["blown"] = sum(1 for e in fu if not e["won"])
    v["close_out"] = _pct(sum(1 for e in fu if e["won"]), len(fu))
    nn["fsu_n"] = len(fu)
    allsets = [s for e in E for s in e["sets"]]
    v["bagels_for"] = sum(1 for a, b in allsets if a == 6 and b == 0)
    v["bagels_against"] = sum(1 for a, b in allsets if a == 0 and b == 6)
    v["breadsticks_for"] = sum(1 for a, b in allsets if a == 6 and b == 1)
    v["breadsticks_against"] = sum(1 for a, b in allsets if a == 1 and b == 6)
    close = [(a, b) for a, b in allsets if max(a, b) >= 7]
    v["close_sets_pct"] = _pct(sum(1 for a, b in close if a > b), len(close))
    nn["close_n"] = len(close)
    # efficiency
    gw = sum(a for a, b in allsets)
    gl = sum(b for a, b in allsets)
    v["games_won_pct"] = _pct(gw, gw + gl)
    v["sets_won_pct"] = _pct(sum(1 for a, b in allsets if a > b), len(allsets))
    v["games_per_set"] = _pct(gw + gl, len(allsets))
    full = [e for e in E if e["status"] == "done" and e["sets"]]
    v["games_per_match"] = an.mean(sum(a + b for a, b in e["sets"]) for e in full)
    wins_full = [e for e in full if e["won"]]
    losses_full = [e for e in full if not e["won"]]
    v["straight_win_pct"] = _pct(sum(1 for e in wins_full if all(a > b for a, b in e["sets"])), len(wins_full))
    v["straight_loss_pct"] = _pct(sum(1 for e in losses_full if all(a < b for a, b in e["sets"])), len(losses_full))
    v["avg_margin"] = an.mean(sum(a - b for a, b in e["sets"]) for e in full)
    wg = sum(a for e in wins_full for a, b in e["sets"])
    wl = sum(b for e in wins_full for a, b in e["sets"])
    v["win_games_pct"] = _pct(wg, wg + wl)
    v["tb_per_set"] = _pct(len(tbl), len(allsets))
    v["duration_avg"] = an.mean(e["dur"] for e in E if e["dur"])
    v["ret_losses"] = sum(1 for e in E if not e["won"] and e["status"] in ("ret", "def"))
    return v, nn


def _style_values(st: dict | None) -> dict:
    if not st:
        return {}
    sv = st.get("serve") or {}
    dr = sv.get("direction") or {}
    rl = st.get("rally") or {}
    sh = st.get("shots") or {}
    nt = st.get("net") or {}
    rt = st.get("return") or {}
    fd, fa = dr.get("first_deuce") or {}, dr.get("first_ad") or {}
    return {"ch_matches": st.get("matches"), "wide_deuce": fd.get("wide"), "t_deuce": fd.get("t"), "body_deuce": fd.get("body"),
            "wide_ad": fa.get("wide"), "t_ad": fa.get("t"), "body_ad": fa.get("body"), "unret_rate": sv.get("unret_rate"),
            "snv_rate": sv.get("snv_rate"), "rally_len": rl.get("mean_len"), "rally_short": (rl.get("dist") or {}).get("1-3"),
            "rally_long": (rl.get("dist") or {}).get("10+"), "won_long": (rl.get("won") or {}).get("10+"),
            "won_short": (rl.get("won") or {}).get("1-3"), "winners_pp": sh.get("winners_per_pt"), "ue_pp": sh.get("ue_per_pt"),
            "w_ue_ratio": sh.get("winner_ue_ratio"), "fh_share": sh.get("fh_share"), "fh_winners_pp": sh.get("fh_winners_per_pt"),
            "bh_winners_pp": sh.get("bh_winners_per_pt"), "net_rate": nt.get("rate"), "net_won": nt.get("won"),
            "ret_deep": (rt.get("depth") or {}).get("deep"), "aggression": st.get("aggression")}


def _strong_split(sr: dict, pid: str, opps_r: list[str], opps_s: list[str]) -> tuple[float | None, float | None]:
    """Hold % v the 20 best returners and break % v the 20 best servers (model, hard court, average level)."""
    from oddsmarkets.tennis.models import serve_return as SR
    try:
        h = [SR.hold_prob(sr, pid, o, "hard", None, 3, calibrated=True) for o in opps_r if o != pid]
        b = [1 - SR.hold_prob(sr, o, pid, "hard", None, 3, calibrated=True) for o in opps_s if o != pid]
        return (sum(h) / len(h) if h else None, sum(b) / len(b) if b else None)
    except Exception:  # noqa: BLE001
        return None, None


# ---------------------------------------------------------------------------------------------- catalogue

def qualified_floor(td: an.TourData, year: int) -> int:
    end = td.season_end(year)
    frac = min(1.0, max(0.15, (end - date(int(year), 1, 1)).days / 330.0))
    return max(8, int(round(20 * frac)))


def form_values(td: an.TourData, year: int, pids: list[str]) -> dict[str, dict]:
    """Elo levels and changes at the season's end, the season's peak, the Elo rank among active players."""
    end = td.season_end(year)
    nxt = end + timedelta(days=1)
    cur = td.elo_at(nxt)
    d30, d90, d365 = td.elo_at(nxt - timedelta(days=30)), td.elo_at(nxt - timedelta(days=90)), td.elo_at(nxt - timedelta(days=365))
    active = {p: r for p, r in cur.items() if r.get("last") and (end - an.day(r["last"])).days <= 365 and (r.get("n") or 0) >= 10}
    order = sorted(active, key=lambda p: -active[p]["all"])
    rank = {p: i + 1 for i, p in enumerate(order)}
    lo, hi = f"{year}-01-01", f"{year}-12-31"
    peak: dict[str, float] = {}
    for g in td.elo.get("rows") or []:
        if g[1] < lo:
            continue
        if g[1] > hi:
            break
        for p, k in ((g[2], 13), (g[3], 15)):
            x = an.fnum(g[k])
            if x is not None and x > peak.get(p, -1e9):
                peak[p] = x
    out = {}
    for p in pids:
        r = cur.get(p)
        if not r:
            continue
        o = {"elo": r["all"], "elo_hard": r["hard"], "elo_clay": r["clay"], "elo_grass": r["grass"], "elo_rank": rank.get(p),
             "elo_peak": peak.get(p)}
        for k, ref in (("elo_d30", d30), ("elo_d90", d90), ("elo_d365", d365)):
            if p in ref:
                o[k] = r["all"] - ref[p]["all"]
        out[p] = o
    return out


def build(td: an.TourData, year: int, entries: dict[str, list[dict]] | None = None, extras: dict[str, dict] | None = None,
          sr: dict | None = None) -> dict:
    """data/<T>/<year>/players.json."""
    sr = sr if sr is not None else td.season_sr(year)
    entries = entries if entries is not None else season_entries(td, year, sr)
    extras = extras or {}
    end = td.season_end(year)
    floor = qualified_floor(td, year)
    tf = titles_finals(td, year)
    pids = [p for p, E in entries.items() if len(E) >= MIN_LIST]
    form = form_values(td, year, pids)
    srp = (sr or {}).get("players") or {}
    # strong returners / servers: the 20 best r and s among players active this season
    act = [p for p in entries if p in srp and (srp[p].get("all") or {}).get("n", 0) >= 10]
    best_r = sorted(act, key=lambda p: -(srp[p]["all"].get("r") or -9))[:20]
    best_s = sorted(act, key=lambda p: -(srp[p]["all"].get("s") or -9))[:20]
    rows: dict[str, dict] = {}
    nns: dict[str, dict] = {}
    surf_vals: dict[str, dict[str, dict]] = {}
    surf_n: dict[str, dict[str, dict]] = {}
    for p in pids:
        E = entries[p]
        rec_all = (srp.get(p) or {}).get("all")
        v, nn = values_from(E, rec_all)
        _apply_titles(v, nn, (tf.get(p) or {}).get("all"))
        for s in an.SURFACES:
            r = (srp.get(p) or {}).get(s)
            if r:
                v[f"hold_{s}"] = r.get("hold")
                v[f"brk_{s}"] = r.get("break")
        if p in srp and sr:
            v["hold_v_strong"], v["brk_v_strong"] = _strong_split(sr, p, best_r, best_s)
        v.update(form.get(p) or {})
        if E:
            v["hot_hand"] = an.mean((e["won"] - e["elo_p"]) for e in E[-10:] if e["elo_p"] is not None)
            best = run = 0
            for e in E:
                run = run + 1 if e["won"] else 0
                best = max(best, run)
            v["best_streak"] = best
            rk = [e["rank"] for e in E if e["rank"]]
            v["best_rank"] = min(rk) if rk else None
            v["rank"] = E[-1]["rank"]
        v.update(_style_values(td.style.get(p)))
        v.update({k: x for k, x in (extras.get(p) or {}).items() if k in BY_KEY})
        rows[p] = v
        nns[p] = nn
        for s in an.SURFACES:
            Es = [e for e in E if e["surface"] == s]
            if not Es:
                continue
            sv, sn = values_from(Es, (srp.get(p) or {}).get(s))
            _apply_titles(sv, sn, (tf.get(p) or {}).get(s))
            surf_vals.setdefault(s, {})[p] = {k: sv.get(k) for k in SURFACE_KEYS}
            surf_vals[s][p].update(elo_surface=v.get(f"elo_{s}"), elo=v.get("elo"))
            surf_n.setdefault(s, {})[p] = sn
    qual = {p for p in pids if rows[p]["matches"] >= floor}
    pct, rank_m = _percentiles(rows, nns, qual, METRICS)
    pct_s: dict[str, dict[str, dict]] = {}
    for s, vals in surf_vals.items():
        fl = SURFACE_FLOOR.get(s, 8)
        q = {p for p, x in vals.items() if (x.get("matches") or 0) >= fl}
        ps, _ = _percentiles(vals, surf_n[s], q, [BY_KEY[k] for k in SURFACE_KEYS + SURFACE_RATING_KEYS])
        for p, d in ps.items():
            if (vals[p].get("matches") or 0) >= _surface_show(s):
                pct_s.setdefault(p, {})[s] = d
    players = {}
    for p in sorted(pids, key=lambda p: (-(rows[p]["matches"] or 0), p)):
        info = td.players.get(p) or {}
        players[p] = {"name": td.name(p), "short": td.short(p), "country": info.get("country"), "age": td.age(p, end),
                      "rank": rows[p].get("rank"), "matches": rows[p]["matches"], "qualified": p in qual,
                      "values": {k: an.fmt_value(rows[p].get(k), BY_KEY[k]["fmt"]) for k in METRIC_KEYS},
                      "pct": pct.get(p, {}), "pct_surface": pct_s.get(p, {}), "rank_metric": rank_m.get(p, {}),
                      "values_surface": {s: {k: an.fmt_value(x, BY_KEY[k]["fmt"]) for k, x in surf_vals[s][p].items() if x is not None}
                                         for s in surf_vals if p in surf_vals[s] and (surf_vals[s][p].get("matches") or 0) >= _surface_show(s)}}
    return {"ok": True, "tour": td.tour, "year": int(year), "updated_at": an.now(), "floor": floor,
            "surface_floor": SURFACE_FLOOR, "metrics": tour_metrics(td.tour), "players": players, "version": VERSION}


def tour_metrics(tour: str) -> list[dict]:
    """The catalogue a tour's pages show: point-level WTA statistics exist only for the WTA."""
    return [m for m in METRICS if not (tour == "atp" and m.get("scope") == "wta_stats")]


def _surface_show(s: str) -> int:
    """Surface blocks (values_surface, pct_surface) are written from half the surface floor up."""
    return max(3, SURFACE_FLOOR.get(s, 8) // 2)


def _percentiles(rows: dict[str, dict], nns: dict[str, dict], qual: set[str], metrics: list[dict]) -> tuple[dict, dict]:
    """({pid: {key: pct}}, {pid: {key: rank}}): each value (shrunk when SHRINK names it) placed against the
    qualified players' shrunk values; ranks among the qualified only."""
    pct: dict[str, dict] = defaultdict(dict)
    rk: dict[str, dict] = defaultdict(dict)
    for m in metrics:
        k, lower = m["key"], bool(m.get("lower"))
        raw = {p: an.fnum(rows[p].get(k)) for p in rows}
        ref_raw = [raw[p] for p in qual if raw.get(p) is not None]
        if len(ref_raw) < 2:
            continue
        prior = sum(ref_raw) / len(ref_raw)
        sh = SHRINK.get(k)

        def adj(p):
            x = raw.get(p)
            if x is None or sh is None:
                return x
            return an.shrink(x, (nns.get(p) or {}).get(sh[0]), prior, sh[1])
        ref = sorted(adj(p) for p in qual if raw.get(p) is not None)
        for p in rows:
            x = adj(p)
            if x is None:
                continue
            pct[p][k] = an.place(ref, x, lower)
            if p in qual:
                rk[p][k] = an.rank_in(ref, x, lower)
    return pct, rk


# ---------------------------------------------------------------------------------------------- peer blocks

# The spec's metric ids per peer group, headline then secondary (docs/_design/metrics/tennis.json, docs/METRICS_SPEC.md
# "Tennis"), and the similar-player weights (YoY r floored at 0.2, capped at 0.8 for ratings and fits).
PEER_KEYS = {
    "atp_all": ["elo", "games_won_pct", "hold", "brk", "win_v_top50", "elo_clay", "elo_grass", "hold_plus_break", "serve_rating",
                "return_rating", "win_pct", "sets_won_pct", "elo_hard", "elo_peak", "avg_opp_elo", "win_v_top10", "win_v_top20",
                "tb_per_set", "games_per_set", "tb_pct", "dec_pct", "close_sets_pct"],
    "wta_all": ["elo", "games_won_pct", "hold", "brk", "dominance", "ace_pct", "win_v_top50", "elo_clay", "elo_grass",
                "hold_plus_break", "serve_rating", "return_rating", "win_pct", "spw_real", "rpw_real", "tpw", "hold_real", "brk_real",
                "first_in", "first_won", "second_won", "df_pct", "elo_hard", "elo_peak", "avg_opp_elo", "tb_pct", "dec_pct",
                "bp_saved_pct", "bp_conv_pct"],
    "atp_hard": ["elo_hard", "games_won_pct", "hold", "brk", "win_pct", "win_v_top50", "elo", "hold_plus_break", "serve_rating",
                 "return_rating", "tb_per_set", "tb_pct", "dec_pct"],
    "atp_clay": ["elo_clay", "elo", "games_won_pct", "hold", "brk", "win_pct", "hold_plus_break", "serve_rating", "return_rating",
                 "win_v_top50", "tb_pct", "dec_pct"],
    "atp_grass": ["elo_grass", "elo", "games_won_pct", "hold", "brk", "win_pct", "hold_plus_break", "serve_rating", "return_rating",
                  "win_v_top50", "tb_per_set", "tb_pct"],
    "wta_hard": ["elo_hard", "games_won_pct", "hold", "brk", "win_pct", "dominance", "ace_pct", "elo", "hold_plus_break", "serve_rating",
                 "return_rating", "win_v_top50", "spw_real", "rpw_real", "first_won", "tb_pct", "bp_saved_pct", "bp_conv_pct"],
    "wta_clay": ["elo_clay", "elo", "games_won_pct", "hold", "brk", "win_pct", "dominance", "ace_pct", "hold_plus_break", "serve_rating",
                 "return_rating", "win_v_top50", "spw_real", "rpw_real", "first_won", "tb_pct", "bp_saved_pct", "bp_conv_pct"],
    "wta_grass": ["elo_grass", "elo", "games_won_pct", "hold", "brk", "win_pct", "ace_pct", "hold_plus_break", "serve_rating",
                  "return_rating", "dominance", "spw_real", "rpw_real", "first_won", "tb_pct"],
}
PEER_HEADLINE = {"atp_all": 7, "wta_all": 9, "atp_hard": 6, "atp_clay": 6, "atp_grass": 6, "wta_hard": 7, "wta_clay": 8, "wta_grass": 7}
SIMILAR_W = {
    "atp_all": {"elo": 0.8, "hold": 0.8, "brk": 0.8, "elo_clay": 0.74, "elo_grass": 0.68, "games_won_pct": 0.72, "tb_per_set": 0.57},
    "wta_all": {"elo": 0.75, "hold": 0.8, "brk": 0.8, "elo_clay": 0.64, "elo_grass": 0.65, "games_won_pct": 0.62, "ace_pct": 0.8,
                "first_in": 0.78},
    "atp_hard": {"elo_hard": 0.8, "hold": 0.8, "brk": 0.8, "games_won_pct": 0.65},
    "atp_clay": {"elo_clay": 0.8, "hold": 0.8, "brk": 0.8, "games_won_pct": 0.52},
    "atp_grass": {"elo_grass": 0.8, "hold": 0.8, "brk": 0.8, "games_won_pct": 0.46},
    "wta_hard": {"elo_hard": 0.8, "hold": 0.8, "brk": 0.8, "games_won_pct": 0.55, "ace_pct": 0.8},
    "wta_clay": {"elo_clay": 0.8, "hold": 0.8, "brk": 0.8, "games_won_pct": 0.47, "ace_pct": 0.74},
    "wta_grass": {"elo_grass": 0.8, "hold": 0.8, "brk": 0.8, "games_won_pct": 0.34, "ace_pct": 0.59},
}
SIMILAR_K = 5


def _num(x) -> float | None:
    x = an.fnum(x)
    return x if x is not None and math.isfinite(x) else None


def similar_players(feats: dict[str, dict], weights: dict[str, float], k: int = SIMILAR_K) -> dict[str, list]:
    """{pid: [[other pid, distance]]} by the spec's recipe. `feats` {pid: {feature: value}} is the pool (players meeting
    the group's minimum); each feature is z-scored within the pool; distance = sqrt(sum w (za - zb)^2 / sum w) over the
    features both players have (a missing feature is dropped and the weights renormalised; at least half the weight
    must remain); the k nearest, nearest first."""
    ids = sorted(feats)
    stats: dict[str, tuple[float, float]] = {}
    for f in weights:
        xs = [v for v in (_num(feats[p].get(f)) for p in ids) if v is not None]
        if len(xs) < 3:
            continue
        m = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) or 1.0
        stats[f] = (m, sd)
    z: dict[str, dict[str, float]] = {}
    for p in ids:
        zp = {}
        for f, (m, sd) in stats.items():
            v = _num(feats[p].get(f))
            if v is not None:
                zp[f] = (v - m) / sd
        z[p] = zp
    w_all = sum(weights[f] for f in stats)
    out: dict[str, list] = {}
    for a in ids:
        za = z[a]
        rows = []
        for b in ids:
            if b == a:
                continue
            zb = z[b]
            s = w = 0.0
            for f, wt in weights.items():
                if f in za and f in zb:
                    s += wt * (za[f] - zb[f]) ** 2
                    w += wt
            if w > 0 and w >= 0.5 * w_all:
                rows.append((math.sqrt(s / w), b))
        rows.sort()
        out[a] = [[b, round(d, 3)] for d, b in rows[:k]]
    return out


def peer_blocks(cat: dict, tour: str) -> dict[str, dict]:
    """{pid: peer block} for a season catalogue `cat` (build()'s payload), written into the career files
    (players/<pid>.json "peer") so the player and compare pages need not load players.json.

    Per peer group of the spec (the tour, then each surface the player has a block on): the group id, its minimum and
    pool size, whether the player meets it, the sample, the spec's metric values (headline ids first, `headline` lists
    them) and, only for players in the pool, their percentiles (surface groups rank Elo among the surface pool, from
    pct_surface.<s>.elo_surface / .elo) and tour ranks; plus the similar players (the tour view and each surface view)
    by the spec's weights."""
    P = cat.get("players") or {}
    floor = cat.get("floor")
    sfl = cat.get("surface_floor") or SURFACE_FLOOR
    T = "WTA" if tour == "wta" else "ATP"
    g_all = f"{tour}_all"
    q = [p for p, r in P.items() if r.get("qualified")]

    def tour_feat(r: dict) -> dict:
        v = r.get("values") or {}
        o = {}
        for f in SIMILAR_W[g_all]:
            x = _num(v.get(f))
            if f in ("elo_clay", "elo_grass"):
                e = _num(v.get("elo"))
                x = None if x is None or e is None else x - e
            o[f] = x
        return o
    sim_all = similar_players({p: tour_feat(P[p]) for p in q}, SIMILAR_W[g_all])
    pools: dict[str, list[str]] = {}
    sim_s: dict[str, dict] = {}
    for s in an.SURFACES:
        fl = sfl.get(s, SURFACE_FLOOR.get(s, 8))
        pools[s] = [p for p, r in P.items() if (((r.get("values_surface") or {}).get(s) or {}).get("matches") or 0) >= fl]
        g = f"{tour}_{s}"
        feats = {}
        for p in pools[s]:
            vs = (P[p].get("values_surface") or {}).get(s) or {}
            feats[p] = {f: ((P[p].get("values") or {}).get(f) if f.startswith("elo") else vs.get(f)) for f in SIMILAR_W[g]}
        sim_s[s] = similar_players(feats, SIMILAR_W[g])

    def named(rows: list) -> list[dict]:
        return [{"id": o, "name": (P.get(o) or {}).get("name") or o, "d": d} for o, d in rows]
    out: dict[str, dict] = {}
    for p, r in P.items():
        v = r.get("values") or {}
        inq = bool(r.get("qualified"))
        keys = PEER_KEYS[g_all]
        groups = {"all": {"group": g_all, "peer_group": f"{T} players with {floor}+ tour-level matches",
                          "minimum": {"field": "matches", "value": floor}, "pool": len(q), "in_pool": inq,
                          "sample": {"matches": r.get("matches"), "stats_matches": v.get("stats_matches")},
                          "headline": keys[:PEER_HEADLINE[g_all]],
                          "values": {k: v.get(k) for k in keys if v.get(k) is not None},
                          "pct": {k: x for k, x in (r.get("pct") or {}).items() if k in keys} if inq else {},
                          "rank": {k: x for k, x in (r.get("rank_metric") or {}).items() if k in keys} if inq else {}}}
        for s in an.SURFACES:
            vs = (r.get("values_surface") or {}).get(s)
            if not vs:
                continue
            g = f"{tour}_{s}"
            fl = sfl.get(s, SURFACE_FLOOR.get(s, 8))
            ins = (vs.get("matches") or 0) >= fl
            ps = (r.get("pct_surface") or {}).get(s) or {}
            keys = PEER_KEYS[g]
            vals, pc = {}, {}
            for k in keys:
                if k.startswith("elo"):
                    x, pk = v.get(k), ("elo_surface" if k == f"elo_{s}" else k)
                else:
                    x, pk = vs.get(k), k
                if x is not None:
                    vals[k] = x
                if ins and ps.get(pk) is not None:
                    pc[k] = ps[pk]
            groups[s] = {"group": g, "peer_group": f"{T} players with {fl}+ tour-level matches on {s}",
                         "minimum": {"field": f"values_surface.{s}.matches", "value": fl}, "pool": len(pools[s]), "in_pool": ins,
                         "sample": {"matches": vs.get("matches")}, "headline": keys[:PEER_HEADLINE[g]], "values": vals, "pct": pc}
        out[p] = {"year": cat.get("year"), "tour": tour, "groups": groups,
                  "similar": named(sim_all.get(p, [])) if inq else [],
                  "similar_surface": {s: named(sim_s[s][p]) for s in an.SURFACES if p in sim_s[s]},
                  "method": "Percentiles: 100 = best among the group's pool (players meeting its minimum); rates are shrunk "
                            "towards the pool mean by a few pseudo-matches before placing. Similar players: weighted Euclidean "
                            "distance on z-scores within the pool (weights = season-to-season reliability, floored at 0.2 and "
                            "capped at 0.8), the 5 nearest; the tour view takes clay and grass Elo as the gap to overall Elo."}
    return out


# ---------------------------------------------------------------------------------------------- careers

def season_summary(E: list[dict], titles_finals: tuple[int, int] | None = None) -> dict:
    w = sum(1 for e in E if e["won"])
    bys = {}
    for s in an.SURFACES:
        x = [e for e in E if e["surface"] == s]
        if x:
            bys[s] = [sum(1 for e in x if e["won"]), sum(1 for e in x if not e["won"])]
    fin = [e for e in E if e["round"] == "F"]
    t, f = titles_finals if titles_finals is not None else (sum(1 for e in fin if e["won"]), len(fin))
    return {"w": w, "l": len(E) - w, "titles": t, "finals": f, "by_surface": bys}


def split_tables(E: list[dict]) -> dict:
    def band(r):
        if r is None:
            return "unranked"
        for k in (10, 20, 50, 100):
            if r <= k:
                return f"top{k}"
        return "100+"
    out = {"surface": {}, "level": {}, "round": {}, "opp_band": {}}
    for e in E:
        for kind, key in (("surface", e["surface"]), ("level", e["level"]), ("round", e["round"]), ("opp_band", band(e["opp_rank"]))):
            d = out[kind].setdefault(str(key), {"w": 0, "l": 0})
            d["w" if e["won"] else "l"] += 1
    return out


def clutch_totals(E: list[dict]) -> dict:
    def agg(items):
        w = sum(1 for x in items if x[0])
        ex = [x[1] for x in items if x[1] is not None]
        return {"w": w, "l": len(items) - w, "exp": round(sum(ex), 2) if ex else None,
                "exp_pct": round(sum(ex) / len(ex), 4) if ex else None}
    return {"tb": agg([t for e in E for t in e["tbs"]]), "deciding": agg([e["dec"] for e in E if e["dec"] is not None]),
            "from_set_down": agg([e["fsd"] for e in E if e["fsd"] is not None])}


def elo_path(td: an.TourData) -> dict[str, list]:
    """{pid: [[date, all, hard, clay, grass]]} after each rated match, thinned to the last value per week."""
    init = td.elo.get("init") or {}
    state: dict[str, list] = {}
    out: dict[str, list] = defaultdict(list)
    si = {"hard": 1, "clay": 2, "grass": 3}
    for g in td.elo.get("rows") or []:
        for pid, ai, sidx in ((g[2], 13, 14), (g[3], 15, 16)):
            st = state.get(pid)
            if st is None:
                v = float(init.get(pid, 1500.0))
                st = state[pid] = [v, v, v, v]
            st[0] = float(g[ai])
            st[si.get(g[4], 1)] = float(g[sidx])
            d = an.day(g[1])
            wk = (d - timedelta(days=d.weekday())).isoformat() if d else g[1]
            row = [g[1][:10], round(st[0], 1), round(st[1], 1), round(st[2], 1), round(st[3], 1)]
            lst = out[pid]
            if lst and lst[-1][0][:10] >= wk and (an.day(lst[-1][0]) - timedelta(days=an.day(lst[-1][0]).weekday())).isoformat() == wk:
                lst[-1] = row
            else:
                lst.append(row)
    return out


def rank_paths(td: an.TourData) -> dict[str, list]:
    """{pid: [[date, rank]]}: the rank each match row carried, thinned to one per week, plus the latest official."""
    seen: dict[str, dict[str, int]] = defaultdict(dict)
    for y in td.years:
        for m in td.matches(y).values():
            d = str(m.get("date") or "")[:10]
            if len(d) != 10:
                continue
            dd = an.day(d)
            wk = (dd - timedelta(days=dd.weekday())).isoformat()
            for p, rk in ((m.get("p1"), m.get("rank1")), (m.get("p2"), m.get("rank2"))):
                r = an.inum(rk)
                if p and r:
                    seen[str(p)][wk] = r
    rk = td.store(td.current).get("rankings") or {}
    if rk.get("date"):
        for row in rk.get("rows") or []:
            seen[str(row[1])][str(rk["date"])[:10]] = int(row[0])
    return {p: [[k, v] for k, v in sorted(d.items())] for p, d in seen.items()}


def h2h_lists(td: an.TourData, top: int = 30) -> dict[str, list]:
    """{pid: [[opp, w, l, last_date]]} (main-draw matches of every level, walkovers excluded), top 30 by meetings."""
    rows: dict[str, list] = defaultdict(list)
    for pair, ms in td.pair_index().items():
        if len(pair) != 2:
            continue
        a, b = sorted(pair)
        wa = sum(1 for m in ms if str(m["winner"]) == a)
        last = str(ms[-1].get("date") or "")[:10]
        rows[a].append([b, wa, len(ms) - wa, last])
        rows[b].append([a, len(ms) - wa, wa, last])
    for v in rows.values():
        v.sort(key=lambda r: r[3], reverse=True)              # most recent first among equal counts
        v.sort(key=lambda r: -(r[1] + r[2]))
    return {p: v[:top] for p, v in rows.items()}


def career_payload(td: an.TourData, pid: str, per_year: dict[int, list[dict]], sr_by_year: dict[int, dict | None],
                   elo_series: list | None, ranks: list | None, results: list[dict], h2h_rows: list | None,
                   defend: list | None, odds: dict | None, current: dict | None, results_all: list | None = None,
                   titles_by_year: dict[int, list | tuple] | None = None) -> dict:
    """`titles_by_year` {year: [titles, finals]} (titles_finals, walkover finals counted); without it the
    played finals are counted."""
    info = td.players.get(pid) or {}
    seasons = []
    allE: list[dict] = []
    for y in sorted(per_year):
        E = per_year[y]
        if not E:
            continue
        allE += E
        tfy = None if titles_by_year is None else tuple(titles_by_year.get(y) or (0, 0))
        row = {"year": int(y), **season_summary(E, tfy)}
        rec = (((sr_by_year.get(y) or {}).get("players") or {}).get(pid) or {}).get("all") or {}
        row["hold"] = an.rnd(rec.get("hold"), 3)
        row["brk"] = an.rnd(rec.get("break"), 3)
        end = td.season_end(y) + timedelta(days=1)
        er = td.elo_at(end).get(pid)
        row["elo_end"] = an.rnd((er or {}).get("all"), 1)
        seasons.append(row)
    sr_path = []
    for y in sorted(sr_by_year):
        recs = ((sr_by_year.get(y) or {}).get("players") or {}).get(pid)
        if not recs or y not in per_year:
            continue
        d = td.season_end(y).isoformat()
        for s in ("all",) + an.SURFACES:
            r = recs.get(s)
            if not r or (s != "all" and not r.get("n")):
                continue
            sr_path.append([d, s, an.rnd(r.get("s"), 3), an.rnd(r.get("r"), 3), an.rnd(r.get("hold"), 3), an.rnd(r.get("break"), 3),
                            an.rnd(r.get("se_s"), 3), an.rnd(r.get("se_r"), 3)])
    st = td.style.get(pid)
    return {"ok": True, "tour": td.tour, "id": pid, "name": td.name(pid), "short": td.short(pid), "country": info.get("country"),
            "hand": info.get("hand"), "dob": info.get("dob"), "height": info.get("height"), "ranks": ranks or [],
            "elo": elo_series or [], "serve_return": sr_path, "seasons": seasons, "results": results,
            "splits": split_tables(allE), "clutch": clutch_totals(allE), "style": st,
            "h2h": h2h_rows or [], "to_defend": defend or [], "odds": odds or {}, "current": current,
            "results_all": results_all or []}


def results_all_rows(td: an.TourData) -> dict[str, list]:
    """{pid: [[date, event, round, surface, opp, won, score]]}: every finished match of every level and year on
    disk (walkovers included, score "w/o"), oldest first; won = 1 / 0."""
    out: dict[str, list] = defaultdict(list)
    for y in td.years:
        for m in td.matches(y).values():
            if m.get("status") not in an.FINISHED or not m.get("winner") or not m.get("p1") or not m.get("p2"):
                continue
            d = str(m.get("date") or "")[:10]
            for side, (me, op) in enumerate(((m["p1"], m["p2"]), (m["p2"], m["p1"]))):
                out[str(me)].append([d, m.get("event"), m.get("round"), m.get("surface"), op, int(str(m["winner"]) == str(me)),
                                     an.score_text(m, flip=side == 1)])
    for v in out.values():
        v.sort(key=lambda r: (r[0], an.ROUND_ORDER.get(r[2], 5)))
    return out


def results_rows(td: an.TourData, pid: str, ms: list[dict], preds: dict) -> list[dict]:
    """The latest results (newest first): main-draw and qualifying matches of every level."""
    out = []
    for m in sorted(ms, key=lambda m: (str(m.get("date") or ""), an.ROUND_ORDER.get(m.get("round"), 5)), reverse=True):
        side = 0 if str(m.get("p1")) == pid else 1
        p = (preds.get(m["id"]) or {}).get("p1_win")
        if p is None:
            p = td.elo_pre(m)
        mk = an.devig2((m.get("odds") or {}).get("ps")) or an.devig2((m.get("odds") or {}).get("avg"))
        won = None if m.get("winner") is None else str(m["winner"]) == pid
        out.append({"match": m["id"], "date": str(m.get("date") or "")[:10], "event": m.get("event"), "round": m.get("round"),
                    "level": m.get("level"), "surface": m.get("surface"), "opp": m.get("p2") if side == 0 else m.get("p1"),
                    "won": won, "status": m.get("status"), "score": an.score_text(m, flip=side == 1),
                    "p_pre": an.prob(None if p is None else (p if side == 0 else 1 - p)),
                    "market_pre": an.prob(None if mk is None else (mk if side == 0 else 1 - mk))})
    return out
