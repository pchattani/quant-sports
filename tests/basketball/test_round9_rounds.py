"""Round 9: playoff rounds come from the bracket's depth, never ESPN's names ("Playoff Series" for every WNBA round
after the first), and each series carries its winner."""
from oddsmarkets.basketball.analytics.season import normalise_rounds, round_label


def _s(a, b, date, wins, summary=None):
    return {"teams": sorted([a, b]), "stype": "post", "games": [{"date": date}], "wins": wins, "round": "Playoff Series",
            **({"summary": summary} if summary else {})}


def test_wnba_three_rounds_named_by_depth():
    fmt = {"rounds": ["r1", "semis", "finals"], "series": [3, 5, 7]}
    s = [_s("1", "8", "2025-09-14", {"1": 2, "8": 0}), _s("4", "5", "2025-09-14", {"4": 1, "5": 2}),
         _s("2", "7", "2025-09-15", {"2": 2, "7": 1}), _s("3", "6", "2025-09-15", {"3": 2, "6": 0}),
         _s("1", "5", "2025-09-21", {"1": 3, "5": 1}), _s("2", "3", "2025-09-21", {"2": 3, "3": 2}),
         _s("1", "2", "2025-10-03", {"1": 4, "2": 1})]
    out = normalise_rounds(s, "wnba", fmt, finished=True)
    assert [x["round"] for x in out] == ["First round"] * 4 + ["Semi-finals"] * 2 + ["WNBA Finals"]
    assert [x["rkey"] for x in out][-1] == "finals"
    assert out[-1]["winner"] == "1" and out[1]["winner"] == "5"
    assert all(x["round_src"] == "Playoff Series" for x in out)


def test_nba_conference_and_unfinished_final():
    fmt = {"rounds": ["r1", "semis", "conf_finals", "finals"], "series": [7, 7, 7, 7]}
    conf = {"a": "East", "b": "East", "c": "West", "d": "West"}
    s = [_s("a", "b", "2026-05-20", {"a": 4, "b": 2}), _s("c", "d", "2026-05-21", {"c": 1, "d": 4}),
         _s("a", "d", "2026-06-04", {"a": 2, "d": 2})]
    # depth: a and d each played one series before -> round 2 of 4 here, with no earlier rounds in the sample
    out = normalise_rounds(s, "nba", fmt, conf, finished=False)
    assert out[0]["conf"] == "East" and out[1]["conf"] == "West"
    assert out[2]["winner"] is None and "conf" not in out[2]
    assert out[0]["winner"] == "a"


def test_round_label_names():
    assert round_label("nba", 4, 4) == "NBA Finals"
    assert round_label("nba", 1, 4) == "First round"
    assert round_label("wnba", 2, 4) == "Second round"
    assert round_label("wnba", 3, 4) == "Semi-finals"
