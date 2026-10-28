"""oddsmarkets/common/performers.py: the league pages' top and bottom performers boards."""
import json

from oddsmarkets.common import performers as P


def _rows(vals, key="x"):
    return [{"id": i, "name": f"P{i}", "team": "T" + str(i % 3), "v": {key: v}} for i, v in enumerate(vals)]


def test_board_top_bottom_and_percentiles():
    b = P.board(_rows([5, 1, 9, 3, 7, 2, 8, 4, 6, 0, 10, 11]), {"key": "x", "label": "X", "dir": "higher", "fmt": "1"})
    assert b["n"] == 12
    assert [r[3] for r in b["top"]] == [11, 10, 9, 8, 7]
    assert [r[5] for r in b["top"]] == [1, 2, 3, 4, 5]
    # the bottom board: the last five in rank order, the very bottom last
    assert [r[3] for r in b["bot"]] == [4, 3, 2, 1, 0]
    assert b["bot"][-1][4] == 0 and b["top"][0][4] == 100
    assert b["top"][0][:3] == ["11", "P11", "T2"]


def test_board_lower_is_better_and_ties():
    b = P.board(_rows([3.0, 1.0, 1.0, 2.0]), {"key": "x", "label": "X", "dir": "lower"}, n=2)
    assert [r[3] for r in b["top"]] == [1.0, 1.0]
    assert [r[5] for r in b["top"]] == [1, 1]          # a tie shares the rank
    assert [r[3] for r in b["bot"]] == [2.0, 3.0]
    assert [r[5] for r in b["bot"]] == [3, 4]


def test_board_small_pools_never_repeat_rows():
    b = P.board(_rows([1, 2, 3, 4, 5, 6, 7]), {"key": "x", "label": "X"})
    ids = [r[0] for r in b["top"]] + [r[0] for r in b["bot"]]
    assert len(ids) == len(set(ids)) == 7
    b = P.board(_rows([1, 2, 3]), {"key": "x", "label": "X"})
    assert len(b["top"]) == 3 and b["bot"] == []
    assert P.board(_rows([1]), {"key": "x", "label": "X"}) is None
    # missing and non-finite values are left out
    rows = _rows([1, 2, 3]) + [{"id": "n", "name": "N", "team": "", "v": {"x": float("nan")}}, {"id": "m", "name": "M", "v": {}}]
    assert P.board(rows, {"key": "x", "label": "X"})["n"] == 3


def test_view_document_and_write(tmp_path):
    rows = _rows([1, 2, 3, 4], "a")
    for r, w in zip(rows, [9, 8, 7, 6]):
        r["v"]["b"] = w
    v = P.view("all", "All players", rows, [{"key": "a", "label": "A", "ours": "GAR"}, {"key": "b", "label": "B"}, {"key": "c", "label": "C"}],
               peer="players", min_text="100 minutes")
    assert [m["key"] for m in v["metrics"]] == ["a", "b"]      # no values for c: no board
    assert v["metrics"][0]["ours"] == "GAR" and "ours" not in v["metrics"][1]
    assert P.view("x", "X", [], [{"key": "a", "label": "A"}]) is None
    doc = P.document([v, None], season="2026", league="nhl")
    assert doc["schema"] == 1 and len(doc["views"]) == 1 and doc["league"] == "nhl"
    size = P.write(tmp_path / "performers.json", doc)
    assert size == len((tmp_path / "performers.json").read_bytes())
    assert json.loads((tmp_path / "performers.json").read_text(encoding="utf-8")) == doc


def test_spec_metrics_order_style_and_ours():
    spec = {"our_models": {"models": {"value": {"name": "Value model"}}, "metrics": {"gar": "value"}},
            "groups": [{"id": "f", "entity": "player", "metrics": [
                {"id": "p60", "display": "Points per 60", "unit": "per 60", "direction": "higher", "set": "headline", "order": 2, "explanation": "Points."},
                {"id": "gar", "display": "Value", "unit": "GAR", "direction": "higher", "set": "headline", "order": 1, "explanation": "Value."},
                {"id": "toi", "display": "Ice time", "unit": "min", "direction": "higher", "set": "headline", "order": 3, "style": True},
                {"id": "ga", "display": "Goals against", "direction": "lower", "set": "headline", "order": 4},
                {"id": "sup", "display": "Supporting", "set": "supporting", "order": 5}]}]}
    ms = P.spec_metrics(spec, "f", fmt={"gar": "+1"})
    assert [m["key"] for m in ms] == ["gar", "p60", "ga"]       # ours first, the style and supporting metrics dropped
    assert ms[0]["ours"] == "Value model" and ms[0]["fmt"] == "+1"
    assert ms[2]["dir"] == "lower"
    assert [m["key"] for m in P.spec_metrics(spec, "f", only={"p60"})] == ["p60"]
    assert P.spec_metrics(spec, "nope") == []
    assert P.load_spec("hockey")["sport"] == "hockey"
