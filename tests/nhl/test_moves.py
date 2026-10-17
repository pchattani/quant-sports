"""Transactions, deals, the pick-value curve and trade ratings (analytics/moves.py) on hand-written ESPN-style rows and
synthetic value payloads; no network."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.nhl.analytics import moves as MV
from oddsmarkets.nhl.analytics import valuation as VV

D = date(2026, 3, 6)


def row(d, abbr, text, espn_id=""):
    return [d, espn_id, abbr, text]


# ---------------------------------------------------------------------------------------------- clauses and types

def test_split_clauses_keeps_abbreviations():
    s = MV.split_clauses("Acquired F Brayden Schenn from St. Louis Blues for a 2026 third-round pick (No. 73). Placed D A.J. Greer on "
                         "injured reserve. Acquired F X Y from the N.Y. Rangers for F Z W.")
    assert len(s) == 3
    assert "St. Louis" in s[0] or "St Louis" in s[0]
    assert s[1].startswith("Placed") and s[2].startswith("Acquired")
    assert MV.split_clauses("Signed F Peyton Krebs to a four-year contract .Acquired F Zac Funk Washington for F Tyler Kopff.")[1].startswith("Acquired")


@pytest.mark.parametrize("text,typ", [
    ("Acquired D Jayden Struble from Montreal in exchange for a 2027 second-round pick", "trade"),
    ("Traded G Pheonix Copley to the Los Angeles Kings in exchange for future considerations", "trade"),
    ("Sent D Nick Blankensburg to Colorado in exchange for a fifth-round pick in the 2027 NHL draft", "trade"),
    ("Sent D David Jiricek to Iowa (AHL)", "recall"),
    ("Recaled D Yan Kuznetsov from Calgary (AHL)", "recall"),
    ("Signed F Patrick Kane to a two-year contract", "signing"),
    ("Agreed to terms with F Ilya Pautov on a three-year entry-level contract", "signing"),
    ("Claimed D Ilya Solovyov off waivers from the Calgary Flames", "claim"),
    ("Waived F/D Mason Geertsen", "waivers"),
    ("Placed RW Trey Fix-Wolansky on waivers", "waivers"),
    ("Placed F Nick Foligno on unconditional waivers for the purpose of terminating his contract", "release"),
    ("Released Fs Nathan Brown, Caelan Joudrey and Nathan Lecompte", "release"),
    ("PLaced F Nick Foligno on injured reserve", "ir"),
    ("Reinstated F Kirby Dach from long-term injured reserve", "ir"),
    ("Fired head coach Adam Foote", "other"),
])
def test_clause_types(text, typ):
    assert MV.clause_type(text) == typ


def test_clubs_with_typos_and_ahl():
    assert MV.club_of("the Philadelphia Flyers") == "PHI"
    assert MV.club_of("NY Rangers") == "NYR"
    assert MV.club_of("Ottowa Senators") == "OTT"
    assert MV.club_of("Philadephia Flyers") == "PHI"
    assert MV.club_of("Utah Mammoth") == "UTA"
    assert MV.club_of("Toronto (AHL)") is None
    assert MV.club_of("Iowa") is None


# ---------------------------------------------------------------------------------------------- assets

def picks(text, d=D):
    return [(p["year"], p["round"], p["overall"], p["cond"], p["inferred_year"]) for p in MV.parse_picks(text, d)[0]]


def test_pick_phrases_and_typos():
    assert picks("a 20227 second-round pick") == [(2027, 2, None, False, False)]
    assert picks("a 2028 first and second-round pick") == [(2028, 1, None, False, False), (2028, 2, None, False, False)]
    assert picks("two 2026 third-round picks (No. 73 and 76)") == [(2026, 3, 73, False, False), (2026, 3, 76, False, False)]
    assert picks("a third-round pick in the 2027 NHL Draft") == [(2027, 3, None, False, False)]
    assert picks("a 2026 thrid-round draft pick") == [(2026, 3, None, False, False)]
    assert picks("a conditional 2029 first-round pick") == [(2029, 1, None, True, False)]
    assert picks("a 2027 conditional first-round draft pick") == [(2027, 1, None, True, False)]
    assert picks("a 2026 2nd round pick (BUF)") == [(2026, 2, None, False, False)]
    assert picks("2 2026 first-round pick") == [(2026, 1, None, False, False), (2026, 1, None, False, False)]
    assert picks("second and fourth-round picks in the 2027 and 2029 drafts") == [(2027, 2, None, False, False), (2029, 4, None, False, False)]
    # no year: the next draft (before late June: this year's)
    assert picks("two conditional first-round draft picks", date(2026, 6, 23)) == [(2026, 1, None, True, True)] * 2
    assert picks("a seventh-round pick", date(2026, 9, 1)) == [(2027, 7, None, False, True)]


def test_assets_players_positions_and_considerations():
    a = MV.parse_assets("Fs Marco Ross and Liam Ohgren, D Zeev Buium and a 2026 first-round pick", D)
    pl = [(x["name"], x["pos"]) for x in a if x["kind"] == "player"]
    assert pl == [("Marco Ross", "F"), ("Liam Ohgren", "F"), ("Zeev Buium", "D")]
    assert [x["kind"] for x in a].count("pick") == 1
    b = MV.parse_assets("future considerations", D)
    assert [x["kind"] for x in b] == ["fc"]
    c = MV.parse_assets("the rights to unsigned draft pick F Max Curran, a conditional 2028 first-round draft pick", D)
    assert any(x["kind"] == "player" and x["name"] == "Max Curran" and x["rights"] for x in c)
    d = MV.parse_assets("LW/RW Bobby McMann and C/RW Marc McLaughlin", D)
    assert [(x["name"], x["pos"]) for x in d] == [("Bobby McMann", "LW"), ("Marc McLaughlin", "C")]


def test_parse_trade_directions():
    t = MV.parse_trade("Acquired D Jayden Struble from Montreal in exchange for a 20227 second-round pick", "NSH", D)
    assert t["cp"] == "MTL" and t["in"][0]["name"] == "Jayden Struble" and t["out"][0]["year"] == 2027
    t = MV.parse_trade("Traded G Pheonix Copley to the Los Angeles Kings in exchange for future considerations", "TBL", D)
    assert t["cp"] == "LAK" and t["out"][0]["name"] == "Pheonix Copley" and t["in"][0]["kind"] == "fc"
    t = MV.parse_trade("Sent D Nick Blankensburg to Colorado in exchange for a fifth-round pick in the 2027 NHL draft", "NSH", D)
    assert t["cp"] == "COL" and t["out"][0]["kind"] == "player" and t["in"][0]["round"] == 5
    t = MV.parse_trade("Acquired F Zac Funk Washington for F Tyler Kopff", "BUF", D)                 # "from" missing
    assert t["cp"] == "WSH" and t["in"][0]["name"] == "Zac Funk" and t["out"][0]["name"] == "Tyler Kopff"
    assert MV.parse_trade("Acquired F A B from Iowa (AHL) for F C D", "MIN", D) is None


def test_parse_row_mixed_clauses():
    cl = MV.parse_row(["2026-03-05", "37", "VGK", "Acquire F Nic Dowd from the Washington Capitals in exchange for G Jesper Vikman, a 2029 "
                       "second-round pick and a 2027 third-round pick. Placed F Mark Stone on injured reserve. Waived Fs Cole Reinhardt and "
                       "Alexander Holtz."])
    assert [c["type"] for c in cl] == ["trade", "ir", "waivers"]
    assert cl[0]["team"] == "VGK" and cl[0]["trade"]["cp"] == "WSH"
    assert [p["name"] for p in cl[2]["players"]] == ["Cole Reinhardt", "Alexander Holtz"]
    assert [p["name"] for p in cl[1]["players"]] == ["Mark Stone"]


# ---------------------------------------------------------------------------------------------- names

def test_name_normalisation_and_matching():
    assert MV.norm_name("Olli Määttä") == MV.norm_name("Olli Maatta")
    assert MV.norm_name("J.J. Peterka") == MV.norm_name("JJ Peterka")
    assert MV.norm_name("Skyler Brind'Amour") == "skyler brindamour"
    assert MV.norm_name("Fix-Wolansky Jr.") == "fix wolansky"
    ix = MV.NameIndex()
    ix.add("1", "Sebastian Aho", "CAR", "C", 20262027)
    ix.add("2", "Sebastian Aho", "NYI", "D", 20262027)
    ix.add("3", "Elias Pettersson", "VAN", "C", 20262027)
    ix.add("4", "Nick Blankenburg", "NSH", "D", 20252026)
    ix.add("5", "Mitchell Marner", "VGK", "R", 20262027)
    assert ix.match("Sebastian Aho", {"NYI"}) == ("2", "exact+club")
    assert ix.match("Sebastian Aho", set(), "D")[0] == "2"
    assert ix.match("Elias Pettersson")[0] == "3"
    assert ix.match("Nick Blankensburg", {"NSH", "COL"}) == ("4", "spelling+club")
    assert ix.match("Mitch Marner", {"VGK"}) == ("5", "surname+club")
    assert ix.match("Mitch Marner", {"TOR"})[0] is None                   # no club in common: not guessed
    assert ix.match("Nobody Atall", {"VGK"}) == (None, "none")


# ---------------------------------------------------------------------------------------------- deals

def _clauses(rows):
    out = []
    for r in rows:
        out += MV.parse_row(r)
    return out


def test_two_rows_one_deal_picks_not_doubled():
    cl = _clauses([row("2026-06-27", "TOR", "Acquired two 2026 third-round picks (No. 73 and 76) from St. Louis Blues for F Brandon Carlo."),
                   row("2026-06-27", "STL", "Acquired F Brandon Carlo from Toronto in exchange for two 2026 third-round picks (No. 73 and 76).")])
    deals = MV.group_deals(cl)
    assert len(deals) == 1
    d = deals[0]
    assert d["teams"] == ["STL", "TOR"]
    pk = [a for a in d["assets"] if a["kind"] == "pick"]
    assert len(pk) == 2 and all(a["to"] == "TOR" and a["from"] == "STL" for a in pk)
    pl = [a for a in d["assets"] if a["kind"] == "player"]
    assert len(pl) == 1 and pl[0]["to"] == "STL"


def test_one_sided_row_and_separate_deals_same_day():
    cl = _clauses([row("2026-03-06", "WSH", "Acquired D Timothy Liljegren from Toronto in exchange for a 2026 fourth-round draft pick. Acquired F "
                       "David Kampf from Vancouver in exchange for a 2026 sixth-round draft pick.")])
    deals = MV.group_deals(cl)
    assert sorted(tuple(d["teams"]) for d in deals) == [("TOR", "WSH"), ("VAN", "WSH")]


def test_three_team_deal_and_no_deadline_chain():
    cl = _clauses([row("2026-03-05", "AAA", "x"),                     # ignored (no club)
                   row("2026-03-05", "BOS", "Acquired F Alpha One from Chicago in exchange for F Beta Two."),
                   row("2026-03-05", "CHI", "Acquired F Beta Two from Boston in exchange for F Alpha One."),
                   row("2026-03-05", "CHI", "Acquired F Gamma Three from Dallas in exchange for F Alpha One.")])
    deals = MV.group_deals(cl)
    assert len(deals) == 1 and deals[0]["teams"] == ["BOS", "CHI", "DAL"]
    # the same pair a day apart, then again with a third club the next day: never one group with a club on two days
    cl2 = _clauses([row("2026-03-04", "BOS", "Acquired F Alpha One from Chicago in exchange for F Beta Two."),
                    row("2026-03-05", "CHI", "Acquired F Alpha One from Boston in exchange for F Delta Four.")])
    assert len(MV.group_deals(cl2)) == 2


# ---------------------------------------------------------------------------------------------- the pick curve, grades

def _vr(seasons, war_of):
    out = {}
    for s in seasons:
        rows = [{"id": str(pid), "war": w, "gar": w * 6, "kind": "S", "toi": 1000.0, "gp": 82, "rate": 0.1, "age": 25.0, "pos": "C", "team": "T"}
                for pid, w in war_of(s).items()]
        out[s] = {"rows": rows, "team_games": 82, "gpw": 6.0, "n_teams": 32}
    return out


def test_pick_curve_monotone_and_counts_unplayed(rink_roots):
    rng = np.random.default_rng(1)
    drafts = {}
    for y in MV.PICK_DRAFTS:
        drafts[y] = {"cols": ["year", "overall", "round", "in_round", "pid", "name", "team", "dob", "pos"],
                     "rows": [[y, p, (p - 1) // 32 + 1, 1, str(y * 1000 + p), f"P{p}", "T", None, "C"] for p in range(1, 225)]}
    seasons = [VV_season for VV_season in (20102011 + 10001 * k for k in range(16))]

    def war_of(s):
        out = {}
        sy = s // 10000
        for y in MV.PICK_DRAFTS:
            if not (y <= sy < y + 7):
                continue
            for p in range(1, 225):
                if p % 3 == 0:                          # a third never play: they count zero
                    continue
                out[y * 1000 + p] = max(0.0, 3.0 / p ** 0.6 + rng.normal(0, 0.1))
        return out
    vr = _vr(seasons, war_of)
    c = MV.pick_curve(drafts, vr)
    assert c["ok"] and c["n_picks"] == len(MV.PICK_DRAFTS) * 224
    pts = [v for _, v in c["points"]]
    assert all(a >= b for a, b in zip(pts, pts[1:]))
    assert c["round_avg"]["1"] > c["round_avg"]["2"] > c["round_avg"]["7"] > 0
    assert MV.curve_value(c, 1) > MV.curve_value(c, 32) > MV.curve_value(c, 200)
    # a future pick is discounted by the seasons until its draft
    v_now = MV.pick_value(c, {"year": 2026, "round": 1, "overall": None}, 20252026)
    v_far = MV.pick_value(c, {"year": 2028, "round": 1, "overall": None}, 20252026)
    assert v_far == pytest.approx(v_now * 0.81, rel=1e-6)


def test_grades():
    assert [MV.grade(x) for x in (0.7, 0.6, 0.5, 0.4, 0.2)] == ["A", "B", "C", "D", "F"]


# ---------------------------------------------------------------------------------------------- ratings

def _logs(pid, team, dates, toi=18.0, season=20252026):
    sk = pd.DataFrame({"season": season, "game_id": range(2025020001, 2025020001 + len(dates)), "date": dates, "gt": "R", "team": team, "opp": "XXX",
                       "home": 1, "pid": int(pid), "pos": "C", "toi": toi})
    return {"sk": sk, "gk": pd.DataFrame(columns=["pid", "team", "date", "gt", "season", "toi"])}


def test_realised_accumulates_after_the_date_for_the_new_club_only():
    vr = {20252026: {"rows": [{"id": "7", "rate": 0.3}], "gpw": 6.0, "team_games": 82}}
    sk = pd.concat([_logs("7", "OLD", ["2026-02-01", "2026-03-01"])["sk"], _logs("7", "NEW", ["2026-03-07", "2026-03-09", "2026-03-11"])["sk"]])
    r = MV.realised(sk, None, vr, "7", "NEW", date(2026, 3, 6), "S", 20252026, 20282029)
    assert r["gp"] == 3 and r["toi"] == pytest.approx(54.0)
    assert r["war"] == pytest.approx(0.3 * 54 / 60 / 6.0)


def test_at_the_time_value_has_no_hindsight(rink_roots):
    """The valuation as of a trade date reads only seasons completed before it and games before it: changing the
    trade season's catalogue or games after the date leaves it unchanged."""
    f = {"reliability": {"S": {"sigma2": 0.07, "tau2": 0.02, "delta2": 0.02}}, "aging": {"S": [[a, 0.0] for a in range(18, 43)]},
         "survival": {"S": {"base": 0.85}}, "minutes": {"S": {"cv": 0.3}}, "avail": {"S": 0.8}}

    def vr(rate_trade_season):
        out = {}
        for s, rate in ((20232024, 0.2), (20242025, 0.3), (20252026, rate_trade_season)):
            out[s] = {"rows": [{"id": "9", "kind": "S", "pos": "C", "gar": rate * 1200 / 60, "toi": 1200.0, "gp": 70, "rate": rate, "age": 26.0}],
                      "team_games": 82, "gpw": 6.0, "n_teams": 32}
        return out
    stores = {20252026: {"games": {str(2025020000 + i): {"game_id": 2025020000 + i, "date": f"2026-0{3 + i // 31}-{1 + i % 28:02d}", "home": "NEW", "away": "OPP"}
                                   for i in range(40)}}}
    before = ["2026-01-10", "2026-02-10"]
    a = VV.AsOf(vr(0.0), f, _logs("9", "OLD", before), stores, date(2026, 10, 16))
    b = VV.AsOf(vr(5.0), f, _logs("9", "OLD", before + ["2026-03-20", "2026-04-01"]), stores, date(2026, 10, 16))
    pa = a.player("9", "NEW", date(2026, 3, 6))
    pb = b.player("9", "NEW", date(2026, 3, 6))
    for k in ("rate", "mpg", "avail", "t_eff", "games"):
        assert pa[k] == pb[k], k
    assert pa["games"][0] > 0
    va, vb = VV.project([pa], f)[0], VV.project([pb], f)[0]
    assert va["total"] == pytest.approx(vb["total"])


def test_rate_deals_shares_and_free_disposal():
    deal = {"id": "d", "date": "2026-03-06", "teams": ["AAA", "BBB"], "text": [],
            "assets": [{"kind": "pick", "year": 2026, "round": 1, "overall": None, "from": "BBB", "to": "AAA"},
                       {"kind": "fc", "from": "AAA", "to": "BBB"}]}
    curve = {"ok": True, "a": 8.0, "b": 0.5, "c": 0.7, "round_avg": {"1": 1.5, "2": 0.5}}

    class NoAsOf:
        def player(self, *a, **k):
            return None
    MV.rate_deals([deal], MV.NameIndex(), NoAsOf(), {}, {}, curve, {}, {"sk": None, "gk": None}, {}, date(2026, 10, 16), {})
    v = deal["values"]
    assert v["AAA"]["share_at"] == 1.0 and v["AAA"]["grade_at"] == "A" and v["BBB"]["grade_at"] == "F"
    assert v["AAA"]["at"] == pytest.approx(1.5 * 0.9)
    assert deal["winner_at"] == "AAA" and not deal["minor"]
