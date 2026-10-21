"""canon.py (builder A extensions): classification, NCAA rounds, college clock, position pools, class years."""
from oddsmarkets.college import canon


def test_classify_basketball_ncaa_headlines():
    assert canon.classify("mbb", 3, "NCAA Men's Basketball Championship - West Region - 1st Round", False, 22) == \
        ("ncaa", "Round of 64", "West")
    assert canon.classify("mbb", 3, "MEN'S BASKETBALL CHAMPIONSHIP - MIDWEST REGION - 1st ROUND AT OKLAHOMA CITY") == \
        ("ncaa", "Round of 64", "Midwest")
    assert canon.classify("wbb", 3, "NCAA Women's Basketball Championship - Regional 2 in Sacramento - 2nd Round") == \
        ("ncaa", "Round of 32", "Regional 2")
    assert canon.classify("mbb", 3, "SYRACUSE REGIONAL AT WORCESTER MA") == ("ncaa", None, "Syracuse")
    assert canon.classify("mbb", 3, "Men's Basketball Championship - Final Four")[:2] == ("ncaa", "Final Four")
    assert canon.classify("mbb", 3, "Men's Basketball Championship - National Championship")[:2] == ("ncaa", "National Championship")


def test_classify_basketball_other_postseason_and_conf_tourneys():
    assert canon.classify("mbb", 3, "NIT - Semifinal") == ("nit", "Semifinal", None)
    assert canon.classify("wbb", 3, "Women's NIT - 1st Round")[0] == "nit"
    assert canon.classify("wbb", 3, "Women's Basketball Invitation Tournament - 1st Round")[0] == "wbit"
    assert canon.classify("mbb", 3, "College Basketball Crown - Quarterfinals")[0] == "post"
    assert canon.classify("wbb", 3, "WBI TOURNAMENT - QUARTERFINAL") == ("post", "Quarterfinal", None)
    assert canon.classify("mbb", 2, "Big Ten Tournament - 3rd Round", True) == ("conf", "3rd Round", None)
    assert canon.classify("mbb", 2, "ACC MEN'S TOURNAMENT - 1ST ROUND AT ATLANTA GA", True) == ("conf", "1st Round", None)
    assert canon.classify("mbb", 2, "Battle 4 Atlantis - Championship", False) == ("reg", None, None)
    assert canon.classify("mbb", 2, "", True) == ("reg", None, None)


def test_classify_football():
    assert canon.classify("cfb", 3, "College Football Playoff First Round Game") == ("cfp", "First Round", None)
    assert canon.classify("cfb", 3, "College Football Playoff Quarterfinal at the Rose Bowl Presented by Prudential")[:2] == \
        ("cfp", "Quarterfinal")
    assert canon.classify("cfb", 3, "College Football Playoff Semifinal at the Vrbo Fiesta Bowl")[:2] == ("cfp", "Semifinal")
    assert canon.classify("cfb", 3, "CFP NATIONAL CHAMPIONSHIP GAME PRES. BY AT&T")[:2] == ("cfp", "National Championship")
    assert canon.classify("cfb", 3, "BCS National Championship Game")[:2] == ("cfp", "National Championship")
    assert canon.classify("cfb", 3, "Pop-Tarts Bowl") == ("bowl", "Pop-Tarts Bowl", None)
    assert canon.classify("cfb", 3, None) == ("bowl", None, None)
    assert canon.classify("cfb", 2, "SEC Championship") == ("conf", "Championship", None)
    assert canon.classify("cfb", 2, None) == ("reg", None, None)


def _g(gid, date, h, a, hs, as_, sh, sa):
    return {"id": gid, "date": date, "stype": "ncaa", "status": "post", "home": h, "away": a, "hs": hs, "as": as_,
            "seeds": {"home": sh, "away": sa}}


def test_ncaa_rounds_from_bracket():
    games = {g["id"]: g for g in [
        _g("ff", "2026-03-17T22:00:00Z", "A", "B", 70, 60, 16, 16),       # First Four
        _g("r1", "2026-03-19T18:00:00Z", "C", "A", 80, 50, 1, 16),        # Round of 64 (A's FF win does not count)
        _g("r2", "2026-03-19T20:00:00Z", "D", "E", 70, 65, 8, 9),
        _g("r3", "2026-03-21T18:00:00Z", "C", "D", 75, 70, 1, 8),         # Round of 32
        _g("ff4", "2026-04-04T22:00:00Z", "C", "X", 70, 60, 1, 1),         # equal seeds late on: not a First Four
    ]}
    games["ff4"]["home"], games["ff4"]["away"] = "C", "X"
    r = canon.ncaa_rounds(games)
    assert r["ff"] == "First Four" and r["r1"] == "Round of 64" and r["r2"] == "Round of 64" and r["r3"] == "Round of 32"
    assert r["ff4"] == "Sweet 16"          # C has two bracket wins by then


def test_clock_halves_and_quarters():
    assert canon.period_len("mbb", 1, 2026) == 1200 and canon.period_len("mbb", 3, 2026) == 300
    assert canon.period_len("wbb", 1, 2015) == 1200 and canon.period_len("wbb", 3, 2015) == 300
    assert canon.period_len("wbb", 3, 2016) == 600 and canon.period_len("wbb", 5, 2016) == 300
    assert canon.game_t("mbb", 2, 0, 2026) == 2400
    assert canon.game_t("wbb", 4, 0, 2020) == 2400 and canon.game_t("wbb", 5, 100, 2020) == 2600
    assert canon.game_t("mbb", 3, 0, 2010) == 2700


def test_pools_and_classes():
    assert [canon.pool("cfb", p) for p in ("QB", "FB", "OT", "LS", "DE", "OLB", "CB", "PK", "P", "ATH", "XYZ")] == \
        ["QB", "RB", "OL", "OL", "DL", "LB", "DB", "K", "P", "ATH", None]
    assert [canon.pool("mbb", p) for p in ("G", "PG", "F", "C", "Guard", None)] == ["G", "G", "F", "C", "G", None]
    assert canon.class_year({"years": 2, "abbreviation": "SO"}) == "SO"
    assert canon.class_year({"years": 5, "abbreviation": "GR"}) == "GR"
    assert canon.class_year({"years": 3, "abbreviation": "RS-SO"}) == "SO"
    assert canon.class_year({"years": 6}) == "GR"
    assert canon.class_year(None) is None


def test_fix_cfb_postseason_semis_bcs_and_conf():
    games = {
        "f": {"id": "f", "date": "2015-01-13T01:30:00Z", "stype": "cfp", "round": "National Championship", "home": "194", "away": "2483",
              "ranks": {"home": 4, "away": 2}, "seeds": {"home": 4, "away": 2}},
        "s1": {"id": "s1", "date": "2015-01-02T01:30:00Z", "stype": "bowl", "round": "Allstate Sugar Bowl", "home": "194", "away": "333",
               "ranks": {"home": 4, "away": 1}, "seeds": None},
        "s2": {"id": "s2", "date": "2015-01-01T22:00:00Z", "stype": "bowl", "round": "Rose Bowl", "home": "2483", "away": "52",
               "ranks": {"home": 2, "away": 3}, "seeds": None},
        "c": {"id": "c", "date": "2014-12-06T21:00:00Z", "stype": "conf", "home": "333", "away": "1"},
    }
    assert canon.fix_cfb_postseason(2014, games) == 2
    assert games["s1"]["stype"] == "cfp" and games["s1"]["round"] == "Semifinal" and games["s1"]["seeds"] == {"home": 4, "away": 1}
    old = {"r": {"id": "r", "date": "2002-01-04T01:00:00Z", "stype": "bowl", "home": "2390", "away": "158"},
           "cc": {"id": "cc", "date": "2001-12-08T20:00:00Z", "stype": "reg", "neutral": True, "home": "a", "away": "b"}}
    teams = {"a": {"member": True, "conference": "8"}, "b": {"member": True, "conference": "8"}}
    canon.fix_cfb_postseason(2001, old, teams)
    assert old["r"]["stype"] == "cfp" and old["r"]["round"] == "National Championship"
    assert old["cc"]["stype"] == "conf"
    assert canon.classify("cfb", 3, "Rose Bowl Game Presented by Northwestern Mutual - CFB Semifinal")[:2] == ("cfp", "Semifinal")


def test_ncaa_regions_from_host_sites():
    def g(i, d, rnd, reg, h, a):
        return {"id": i, "date": d, "stype": "ncaa", "round": rnd, "region": reg, "home": h, "away": a}
    games = {x["id"]: x for x in [
        g("a", "2019-03-22", "Round of 64", "Waco", "A", "B"), g("b", "2019-03-24", "Round of 32", "Waco", "A", "C"),
        g("c", "2019-03-29", "Sweet 16", "Greensboro", "A", "D"), g("d", "2019-03-29", "Sweet 16", "Albany", "E", "F"),
        g("e", "2019-03-29", "Sweet 16", "Chicago", "G", "H"), g("f", "2019-03-29", "Sweet 16", "Portland", "I", "J"),
        g("x", "2019-03-22", "Round of 64", "Iowa City", "Q", "R")]}
    assert canon.ncaa_regions(games) == 2
    assert games["a"]["region"] == games["b"]["region"] == "Greensboro"
    assert games["x"]["region"] == "Iowa City"          # nothing later to learn from: left as given
