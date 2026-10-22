"""Round 3 (22 Oct 2026): Wikipedia Challenger draws, the Challenger rows, the schedule and form terms."""
from __future__ import annotations

import html
import json
import math

import numpy as np

from oddsmarkets.tennis import canon
from oddsmarkets.tennis.models import challengers as C
from oddsmarkets.tennis.models import predict as P
from oddsmarkets.tennis.models import sched as SC
from oddsmarkets.tennis.sources import wikipedia as W


def _bracket(name: str, params: dict) -> str:
    mw = {"parts": [{"template": {"target": {"wt": name + "\n"},
                                  "params": {k: {"wt": v} for k, v in params.items()}}}]}
    return "<table data-mw='" + html.escape(json.dumps(mw), quote=True).replace("&#x27;", "&apos;") + "'></table>"


def _page() -> str:
    finals = {"RD1": "Semifinals", "RD2": "Final",
              "RD1-team1": "'''{{flagicon|FRA}} [[Hugo Gaston]]'''", "RD1-score1-1": "'''7<sup>7</sup>'''",
              "RD1-score1-2": "'''6'''",
              "RD1-team2": "{{flagicon|FRA}} [[Kyrian Jacquet]]", "RD1-score2-1": "6<sup>3</sup>", "RD1-score2-2": "4",
              "RD1-team3": "{{flagicon|BEL}} [[Raphaël Collignon]]", "RD1-score3-1": "'''6'''", "RD1-score3-2": "2",
              "RD1-score3-3": "2",
              "RD1-team4": "'''{{flagicon|FRA}} [[Alexandre Müller]]'''", "RD1-score4-1": "1", "RD1-score4-2": "'''6'''",
              "RD1-score4-3": "'''6'''",
              "RD2-team1": "'''{{flagicon|FRA}} [[Hugo Gaston]]'''", "RD2-score1-1": "'''6'''", "RD2-score1-2": "3r",
              "RD2-team2": "{{flagicon|FRA}} [[Alexandre Müller]]", "RD2-score2-1": "2", "RD2-score2-2": "2"}
    half = {"RD1": "Quarterfinals", "RD2": "Semifinals",
            "RD1-team01": "'''{{flagicon|FRA}} [[Hugo Gaston|H Gaston]]'''", "RD1-score01-1": "'''6'''",
            "RD1-score01-2": "'''7'''",
            "RD1-team02": "{{flagicon|ESP}} [[Daniel Rincón (tennis)|D Rincón]]", "RD1-score02-1": "0",
            "RD1-score02-2": "6<sup>9</sup>",
            "RD1-team03": "{{flagicon|FRA}} K Jacquet", "RD1-score03-1": "'''6'''", "RD1-score03-2": "'''6'''",
            "RD1-team04": "Bye",
            "RD2-team01": "'''{{flagicon|FRA}} [[Hugo Gaston|H Gaston]]'''", "RD2-score01-1": "'''7<sup>7</sup>'''",
            "RD2-score01-2": "'''6'''",
            "RD2-team02": "{{flagicon|FRA}} [[Kyrian Jacquet|K Jacquet]]", "RD2-score02-1": "6<sup>3</sup>",
            "RD2-score02-2": "4"}
    return "<html>" + _bracket("4TeamBracket-Tennis3", finals) + _bracket("4TeamBracket-Compact-Tennis3", half) + "</html>"


def test_parse_draw_rounds_winners_and_tiebreaks():
    ms = W.parse_draw(_page())
    by = {(m["round"], frozenset((m["a"], m["b"]))): m for m in ms}
    # the half's semi-final repeats the Finals bracket's: kept once
    assert sum(1 for m in ms if m["round"] == "SF") == 2
    f = by[("F", frozenset(("Hugo Gaston", "Alexandre Müller")))]
    assert f["winner"] == "a" and f["status"] == "ret" and f["sets"][0][:2] == [6, 2]
    sf = by[("SF", frozenset(("Hugo Gaston", "Kyrian Jacquet")))]
    assert sf["sets"][0] == [7, 6, 7, 3]                  # both tiebreak scores shown
    qf = by[("QF", frozenset(("Hugo Gaston", "Daniel Rincón")))]
    assert qf["sets"][1] == [7, 6, 11, 9]
    assert qf["winner"] == "a" and qf["flag_b"] == "ESP"
    assert ("QF", frozenset(("K Jacquet", "Bye"))) not in by        # byes are not matches


def test_tiebreak_loser_only():
    ms = W.parse_draw(_page())
    qf = [m for m in ms if m["round"] == "QF" and "Daniel Rincón" in (m["a"], m["b"])][0]
    # the second set shows "6<sup>9</sup>" for the loser only and 6 for the winner: the winner's points are 11
    assert qf["sets"][1][2:] == [11, 9]


def test_parse_season_week_and_singles():
    page = ('<table class="wikitable"><tr><th>Week of</th><th>Tournament</th></tr>'
            '<tr><td rowspan="2">January 8</td><td><a href="https://en.wikipedia.org/wiki/2018_Bangkok_Challenger_II">'
            'Bangkok Challenger II</a><br/><a href="https://en.wikipedia.org/wiki/Bangkok">Bangkok</a>, Thailand<br/>'
            'Hard (i) – $50,000 – 32S/32Q/16D<br/><a href="https://en.wikipedia.org/wiki/'
            '2018_Bangkok_Challenger_II_%E2%80%93_Singles">Singles</a> – Doubles</td></tr></table>')
    s = W.parse_season(page, 2018)
    assert s == [{"title": "2018 Bangkok Challenger II", "name": "Bangkok Challenger II", "week": "2018-01-08",
                  "city": "Bangkok", "country": "Thailand", "surface": "hard", "indoor": True, "draw": 32,
                  "singles": "2018 Bangkok Challenger II – Singles", "info": "Hard (i) – $50,000 – 32S/32Q/16D"}]
    assert W.round_day("2018-01-08", "F") == "2018-01-14" and W.round_day("2018-01-08", "R32") == "2018-01-10"


def test_name_variants_and_abbreviations():
    assert "Laslo Djere" in C._variants("Laslo Đere")
    assert "Lee Duckhee" in C._variants("Lee Duck-hee")
    full = C._full_names([{"matches": [{"a": "Evan Song", "flag_a": "USA", "b": "E Song", "flag_b": "USA"}]}])
    assert C._expand("E Song", "USA", full) == "Evan Song"
    assert C._expand("E Song", "CAN", full) == "E Song"


def test_resolver_links_by_name_and_country_without_creating():
    reg = canon.Registry("atp", {"players": {
        "1": {"name": "Daniel Evans", "first": "Daniel", "last": "Evans", "country": "GBR", "aliases": []},
        "2": {"name": "Gonzalo Oliveira", "first": "Gonzalo", "last": "Oliveira", "country": "VEN", "aliases": []}}})
    r = C.Resolver(reg)
    assert r("Dan Evans", "GBR") == "1"
    assert r("Gonçalo Oliveira", "POR") == "wk:goncalo-oliveira"          # another player: not linked
    assert len(reg.players) == 2


def test_rank_before_is_strictly_earlier():
    idx = C._rank_index([{"date": "2018-01-01", "p1": "a", "p2": "b", "rank1": 150, "rank2": 90},
                         {"date": "2018-03-01", "p1": "a", "p2": "c", "rank1": 120, "rank2": 50}])
    from datetime import date
    d = date(2018, 3, 1).toordinal()
    assert C._rank_before(idx, "a", d) == 150                # the same-day row is not used
    assert C._rank_before(idx, "a", d + 1) == 120
    assert C._rank_before(idx, "b", date(2018, 6, 1).toordinal()) is None   # more than RANK_DAYS old


def _m(i, d, p1, p2, w, st="done", pts=(None, None), ev="e"):
    return {"id": i, "date": d, "p1": p1, "p2": p2, "winner": w, "status": st, "pts1": pts[0], "pts2": pts[1],
            "event": ev, "round": "R32"}


def test_sched_features_definitions():
    ms = [_m("1", "2020-01-01", "a", "b", "a", pts=(1000, 500)),
          _m("2", "2020-01-05", "a", "c", "c", st="ret"),           # a retired
          _m("3", "2020-01-06", "b", "c", "b", st="wo"),            # walkovers count for nothing
          _m("4", "2020-01-10", "a", "b", None, st="upcoming")]
    r = SC.run(ms, {"1": 0.6, "2": 0.5})
    x = r["pre"]["4"]
    assert math.isclose(x[0], math.log(5) - math.log(9), abs_tol=1e-6)        # rest: 5 days v 9 days
    assert math.isclose(x[1], (2 - 1) / 5, abs_tol=1e-9)                      # m30
    assert math.isclose(x[2], math.log(1000) - math.log(500), abs_tol=1e-6)   # latest points
    assert x[4] == 1.0                                                        # a retired last time
    assert math.isclose(x[5], (1 - 0) / 4, abs_tol=1e-9)                      # h2h
    lam = 0.5 ** (1 / 8)
    fa = (lam * 0.4 + (0 - 0.5)) / (lam + 1 + 1)
    fb = (0 - 0.4) / 2
    assert math.isclose(x[3], 5 * (fa - fb), abs_tol=1e-6)
    a = SC.features(r["current"]["a"], r["current"]["b"], 1, 0, None, assumed=True)
    assert a[0] == 0.0 and a[4] == 0.0


def test_fit_blend_with_schedule_terms_and_blend():
    rng = np.random.default_rng(0)
    n = 4000
    e = rng.uniform(0.2, 0.8, n)
    s = rng.uniform(0.2, 0.8, n)
    x = rng.normal(0, 1, (n, 6))
    z = 0.5 * P.logit(e) + 0.5 * P.logit(s) + 0.3 * x[:, 1]
    y = (rng.uniform(size=n) < P.sigmoid(z)).astype(int)
    f = P.fit_blend(e, s, y, xmat=x.tolist(), x_ridge=1.0)
    assert set(f["w_x"]) == set(SC.FEATS)
    assert abs(f["w_x"]["m30"] - 0.3) < 0.1 and abs(f["w_x"]["rest"]) < 0.1
    p = P.blend(0.6, 0.6, 0.5, 0.5, xdot=SC.dot([0, 1, 0, 0, 0, 0], {"m30": 0.3}))
    assert math.isclose(float(p), float(P.sigmoid(P.logit(0.6) + 0.3)), abs_tol=1e-9)


def test_parse_season_day_month_and_new_year_week():
    page = ('<table class="wikitable"><tr><td rowspan="2">31 December</td><td><a href="https://en.wikipedia.org/wiki/'
            '2013_Aberto_de_S%C3%A3o_Paulo">Aberto de São Paulo</a><br/>São Paulo, Brazil<br/>Regular series<br/>'
            '$125,000+H – hard – 32S/32Q/16D<br/><a href="https://en.wikipedia.org/wiki/2013_Aberto_de_S%C3%A3o_Paulo_'
            '%E2%80%93_Singles">Singles</a></td></tr></table>')
    s = W.parse_season(page, 2013)
    assert s[0]["week"] == "2012-12-31" and s[0]["surface"] == "hard" and s[0]["singles"].endswith("– Singles")


def test_charted_break_points_server_first():
    from oddsmarkets.tennis.analytics import charted as CHD
    assert CHD._bp("30-40") and CHD._bp("40-AD") and CHD._bp("0-40")
    assert not CHD._bp("40-40") and not CHD._bp("40-30") and not CHD._bp("AD-40") and not CHD._bp("3-2")
