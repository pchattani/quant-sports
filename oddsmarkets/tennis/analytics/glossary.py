"""
data/glossary.json: a definition for every catalogue metric and every model term the site uses.
`{"groups": [{"name","entries":[{key,label,desc,fmt,lower,scope,group,kind}]}], "model": [{key,label,group,desc}]}`.
A test checks that every catalogue key has an entry with a description.
"""
from __future__ import annotations

from oddsmarkets.tennis import analytics as an

TL = "Tour-level main-draw matches (Slams, Finals, Masters / 1000s, 500s, 250s, Olympics / United Cup) that were played; walkovers excluded."
INF = " Inferred from game and set scores by the serve/return model (fitted through the season's end), against the average tour-level opponent."
WTA = " From the official WTA match statistics (women's matches with stats only)."
CH = " Match Charting Project career profile (charted matches only; CC BY-NC-SA 4.0)."
EXP = " Expected = the model's calibrated value against the actual opponents, weighted by the points or games played."

DESC = {
    "matches": TL, "wins": "Wins in " + TL.lower(), "losses": "Losses in tour-level main-draw matches.",
    "win_pct": "Wins / matches.", "win_slam": "Win % at the Grand Slams.", "win_m1000": "Win % at ATP Masters 1000 / WTA 1000 events.",
    "win_500": "Win % at 500-level events.", "win_250": "Win % at 250-level events.",
    "win_v_top10": "Win % against opponents ranked in the top 10 at the time of the match.", "wins_top10": "Wins over top-10 opponents.",
    "win_v_top20": "Win % against top-20 opponents.", "win_v_top50": "Win % against top-50 opponents.",
    "titles": "Tour-level titles.", "finals": "Tour-level finals reached.", "final_win_pct": "Finals won / finals played.",
    "slam_wins": "Match wins at the Grand Slams.",
    "upsets": "Wins when the pre-match Elo probability was below 40 %.",
    "upset_losses": "Losses when the pre-match Elo probability was above 60 %.",
    "wins_over_exp": "Wins minus the sum of pre-match Elo win probabilities (walk-forward: each probability uses only results before "
                     "the match). Positive = winning more than the ratings expected.",
    "woe_pm": "Wins over expected per match.", "avg_opp_elo": "Mean overall Elo of the opponents before each match.",
    "win_hard": "Win % on hard courts (carpet folds into hard).", "win_clay": "Win % on clay.", "win_grass": "Win % on grass.",
    "win_indoor": "Win % indoors.",
    "hold": "Hold % (chain scale): P(holding serve)." + INF, "serve_rating": "Serve strength s (logit scale): how much more than the tour "
            "baseline the player holds." + INF, "spw_exp": "Serve points won % implied by the hold rate (inverse of the game formula, "
            "with the tour's point-link offset)." + INF, "serve_se": "Standard error of the serve rating (Laplace approximation): "
            "lower = more evidence.",
    "hold_hard": "Hold % on hard courts." + INF, "hold_clay": "Hold % on clay." + INF, "hold_grass": "Hold % on grass." + INF,
    "hold_v_strong": "Calibrated hold % against the 20 best returners of the season (hard court, average level).",
    "brk": "Break %: P(breaking serve)." + INF, "return_rating": "Return strength r (logit scale)." + INF,
    "rpw_exp": "Return points won % implied by the break rate." + INF, "return_se": "Standard error of the return rating.",
    "brk_hard": "Break % on hard courts." + INF, "brk_clay": "Break % on clay." + INF, "brk_grass": "Break % on grass." + INF,
    "brk_v_strong": "Calibrated break % against the 20 best servers of the season (hard court, average level).",
    "sr_total": "Serve rating + return rating: overall strength on the serve/return scale.",
    "hold_plus_break": "Hold % + break %: above 100 % wins more service and return games combined than an average player.",
    "stats_matches": "Matches with official WTA statistics." + WTA,
    "ace_pct": "Aces / serve points." + WTA, "df_pct": "Double faults / serve points." + WTA, "first_in": "First serves in / serve points." + WTA,
    "first_won": "Points won on the first serve / first serves in." + WTA, "second_won": "Points won on the second serve / second serves." + WTA,
    "spw_real": "Serve points won / serve points." + WTA, "hold_real": "Service games held / service games (breaks = break points "
                "faced - saved)." + WTA, "bp_saved_pct": "Break points saved / faced." + WTA,
    "bp_faced_pg": "Break points faced per service game." + WTA, "aces_pm": "Aces per match." + WTA, "dfs_pm": "Double faults per match." + WTA,
    "spw_vs_exp": "Serve points won % minus expected." + WTA + EXP, "hold_vs_exp": "Hold % minus expected." + WTA + EXP,
    "rpw_real": "Return points won / opponents' serve points." + WTA, "brk_real": "Breaks / opponents' service games." + WTA,
    "bp_conv_pct": "Break points converted / break points." + WTA, "bp_opps_pg": "Break points earned per return game." + WTA,
    "tpw": "Total points won %." + WTA, "dominance": "Return points won % / serve points lost %: above 1 wins return points at a "
           "higher rate than losing serve points." + WTA, "rpw_vs_exp": "Return points won % minus expected." + WTA + EXP,
    "brk_vs_exp": "Break % minus expected." + WTA + EXP,
    "tb_w": "Tiebreaks won (complete sets).", "tb_l": "Tiebreaks lost.", "tb_pct": "Tiebreaks won / played.",
    "tb_exp": "Mean P(win the tiebreak) from the exact chain with the match's serve-point probabilities (first server averaged; "
              "a deciding-set match tiebreak to 10 where the rules say so).",
    "tb_over": "Tiebreaks won minus the sum of their chain probabilities: clutch in tiebreaks.",
    "dec_w": "Deciding sets won (final sets of completed matches that went the distance).", "dec_l": "Deciding sets lost.",
    "dec_pct": "Deciding sets won / played.", "dec_over": "Deciding sets won minus the chain's P(win the set) under its rule.",
    "fsd_w": "Matches won after losing the first set.", "fsd_pct": "Matches won / matches in which the first set was lost.",
    "fsd_over": "Comebacks minus the chain's P(win | a set down), summed over the matches in which the player lost the first set.",
    "blown": "Matches lost after winning the first set.", "bagels_for": "Sets won 6-0.", "bagels_against": "Sets lost 0-6.",
    "breadsticks_for": "Sets won 6-1.", "breadsticks_against": "Sets lost 1-6.",
    "close_sets_pct": "Share of 7-5 and 7-6 sets won.",
    "games_won_pct": "Games won / games played (complete sets).", "sets_won_pct": "Sets won / complete sets.",
    "games_per_set": "Games per complete set.", "games_per_match": "Games per completed match.",
    "straight_win_pct": "Share of completed wins without dropping a set.", "straight_loss_pct": "Share of completed losses without taking a set.",
    "avg_margin": "Games won minus games lost per completed match.", "win_games_pct": "Games won % in completed wins.",
    "close_out": "Matches won / matches in which the first set was won.", "tb_per_set": "Tiebreaks per complete set.",
    "duration_avg": "Mean match duration in minutes where the source gives it.", "ret_losses": "Matches lost by retirement or default.",
    "elo": "Overall Elo after the season's last match (FiveThirtyEight-style surface Elo, B's fitted constants).",
    "elo_hard": "Hard-court Elo.", "elo_clay": "Clay Elo.", "elo_grass": "Grass Elo.",
    "elo_rank": "Rank by overall Elo among players with a rated match in the past year and at least 10 rated matches.",
    "elo_peak": "Highest overall Elo after a match in the season.", "elo_d30": "Overall Elo change over the last 30 days of the season.",
    "elo_d90": "Elo change over 90 days.", "elo_d365": "Elo change over 365 days.",
    "hot_hand": "Mean of (won - pre-match Elo probability) over the last 10 matches.", "best_streak": "Longest run of tour-level wins in the season.",
    "ch_matches": "Charted matches." + CH, "wide_deuce": "First serves wide in the deuce court." + CH, "t_deuce": "First serves down the T, deuce court." + CH,
    "body_deuce": "First serves to the body, deuce court." + CH, "wide_ad": "First serves wide, ad court." + CH,
    "t_ad": "First serves down the T, ad court." + CH, "body_ad": "First serves to the body, ad court." + CH,
    "unret_rate": "Share of serves not returned (aces included)." + CH, "snv_rate": "Serve-and-volley share of serve points." + CH,
    "rally_len": "Mean rally length in shots." + CH, "rally_short": "Share of points of 1-3 shots." + CH,
    "rally_long": "Share of points of 10+ shots." + CH, "won_long": "Points won in rallies of 10+ shots." + CH,
    "won_short": "Points won in rallies of 1-3 shots." + CH, "winners_pp": "Winners per point played." + CH,
    "ue_pp": "Unforced errors per point." + CH, "w_ue_ratio": "Winners / unforced errors." + CH,
    "fh_share": "Forehand share of groundstrokes." + CH, "fh_winners_pp": "Forehand winners per point." + CH,
    "bh_winners_pp": "Backhand winners per point." + CH, "net_rate": "Share of points with a net approach." + CH,
    "net_won": "Points won at the net." + CH, "ret_deep": "Share of returns landing deep." + CH,
    "aggression": "Aggression score: winners plus induced forced errors plus unforced errors per point, the share of points the "
                  "player ends on their own racquet." + CH,
    "rank": "Official ranking.", "best_rank": "Best ranking carried into a match in the season.",
    "points": "Official ranking points (current season).", "race_pts": "Points earned in this season's counted events (Slams, Finals, "
              "1000s, 500s, 250s; no qualifying, Challenger / WTA 125 or best-of-N rule).",
    "to_defend": "Points from last season's counted events still inside the 52 weeks.",
    "proj_rank": "Year-end rank by mean simulated year-end points (season simulation).",
    "p_finals": "Probability of qualifying for the ATP / WTA Finals (season simulation).", "p_no1": "Probability of finishing the year No. 1.",
}

MODEL = [
    ("elo", "Surface Elo", "Ratings", "Overall and per-surface ratings (hard, clay, grass) with K = a / (n + b)^c decaying in matches "
     "played, a fitted surface blend w (a match uses w x surface + (1 - w) x overall), a best-of-five sharpening, a pull towards 1500 "
     "after layoffs and entry ratings from the ranking. Every constant fitted on 2005-2019 walk-forward log-loss."),
    ("serve_return", "Serve/return model", "Ratings", "logit P(i holds v j) = baseline (surface, indoor, best of five, level) + s_i - r_j "
     "with per-surface deviations, fitted by penalised maximum likelihood on the exact probability of every observed set score "
     "(an exact dynamic programme over service games; the first server is unknown, so both orders are mixed), time-decayed. The WTA "
     "fit adds the official point and game statistics as binomial terms."),
    ("chain_hold", "Chain-scale hold", "Ratings", "The hold probability whose i.i.d. point/game/set chain reproduces observed "
     "scorelines (used for the match forecasts); the displayed calibrated hold adds the tour's offset learned from real WTA stats."),
    ("match_chain", "Match chain", "Matches", "Exact Markov chain point -> game -> tiebreak -> set -> match from the two serve-point "
     "probabilities: win probability, set-score, total-games and game-handicap distributions, tiebreak and straight-sets "
     "probabilities; deciding-set rules by event and year (advantage, tiebreak to 7, to 10, at 12-12)."),
    ("blend", "Model probability", "Matches", "logit p = w_elo logit(Elo p) + w_sr logit(serve/return p), weights fitted on walk-forward "
     "predictions; the serve-point pair is then shifted so the chain returns p, with a small match-level dispersion for distributions."),
    ("live_wp", "Live win probability", "Matches", "The same chain from the current score (sets, games, server, points); the serve-point "
     "probabilities are held at their pre-match values. Finished matches replay the most likely game order when only set scores "
     "are known (marked as reconstructed)."),
    ("leverage", "Leverage", "Matches", "P(win | win the game) - P(win | lose it) before a game."),
    ("excitement", "Excitement", "Matches", "The sum of absolute win-probability changes along the match."),
    ("comeback", "Comeback", "Matches", "The winner's lowest win probability during the match."),
    ("tournament_sim", "Tournament simulation", "Tournaments", "20,000 Monte Carlo runs of the real bracket (round robin for the Finals) "
     "with results so far fixed and each remaining match forecast by the model; the 'if the player wins' chances are reweighted so they "
     "measure the match itself."),
    ("season_sim", "Season simulation", "Rankings", "The rest of the calendar played many times: entry probabilities by level and history, "
     "seeded draws, the real points tables and 52-week drops, the Finals round robin. Gives Finals qualification, year-end No. 1 and "
     "ranking distributions."),
    ("draw_difficulty", "Draw difficulty", "Tournaments", "Mean expected opponent Elo along the bracket path from the bracket recursion "
     "with Elo probabilities at the start of the event."),
    ("markets", "Market reference", "Markets", "A quiet reference beside our forecasts, never the headline: Kalshi and Polymarket "
     "two-sided midpoints (spread <= 12c), with the margin removed across a field; a field is shown only when enough runners are "
     "quoted. The closing lines (Pinnacle and the bookmakers' average) from tennis-data.co.uk, with the margin removed "
     "multiplicatively."),
    ("percentile", "Percentiles", "Catalogue", "100 = best among the season's qualified players (a matches floor scaled to the season "
     "played), reversed where lower is better; rates are shrunk towards the pool mean by a few pseudo-matches before placing. The "
     "surface view compares players with enough matches on that surface."),
    ("backtest", "Backtest", "Calibration", "Walk-forward from 2010: ratings use only earlier results, the serve/return model is refitted "
     "monthly, blend weights come from earlier years; scored by log-loss and Brier, beside Pinnacle's closing line (margin removed) as "
     "the market reference."),
    ("charting", "Match Charting Project", "Data", "Shot-by-shot records of selected matches by volunteers (Tennis Abstract), "
     "CC BY-NC-SA 4.0; style profiles derived here are shared under the same licence."),
]


def build_glossary() -> dict:
    from oddsmarkets.tennis.analytics import players as PL
    groups: dict[str, list] = {}
    for m in PL.METRICS:
        groups.setdefault(f"Players: {m['group']}", []).append({**m, "desc": m.get("desc") or DESC.get(m["key"]) or m["label"],
                                                               "kind": "player"})
    model = list(MODEL)
    try:                                   # the Value section's entries (analytics/value.py)
        from oddsmarkets.tennis.analytics import value as VL
        for e in VL.VALUE_GLOSSARY:
            groups.setdefault(e["group"], []).append({"lower": False, "scope": "all", **e, "kind": "value"})
        model += VL.VALUE_MODEL_TERMS
    except Exception:  # noqa: BLE001 - the catalogue's glossary never depends on the Value section
        pass
    return {"ok": True, "updated_at": an.now(), "groups": [{"name": k, "entries": v} for k, v in groups.items()],
            "model": [{"key": k, "label": l, "group": g, "desc": d} for k, l, g, d in model]}
