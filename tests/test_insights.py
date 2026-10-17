"""
The analytics.json insights: the formation optimiser picks the best shape and
orders the eleven, the team and player of the week obey the minutes rules and
tie-breaks, the awards need a qualifier, expected points come from a Poisson
score matrix, team metrics read the opponent's row, percentiles are
direction-aware, and every section degrades to empty on empty input.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oddsmarkets.football.analytics import insights as ins  # noqa: E402
from oddsmarkets.football.analytics.glossary import TEAM_METRICS  # noqa: E402

TOP_KEYS = {"updated_at", "minutes_floor", "season", "rounds", "season_xi", "performers", "teams", "team_metrics", "player_metrics"}
PLAYER_LINE = {"id", "name", "team", "pos", "rt", "g", "a", "xg", "xa", "min", "gid", "opp", "ha", "gf", "ga"}
TEAM_AWARD = {"team", "opp", "ha", "gf", "ga", "xg", "xga", "value", "gid"}


# ── fixtures ─────────────────────────────────────────────────────────────────

def _cand(pos: str, score: float, name: str | None = None) -> dict:
    name = name or f"{pos}{score}"
    return {"pos": pos, "score": score, "key": (-score, name), "line": {"name": name, "pos": pos, "rt": score}}


def _row(gid: str, team: str, opp: str, ha: str, gf: int, ga: int, pos: str, **stats) -> dict:
    row = {"gid": gid, "date": f"2026-09-0{gid}T15:00:00Z", "round": int(gid), "stage": "league", "team": team, "opp": opp,
           "ha": ha, "gf": gf, "ga": ga, "res": "W" if gf > ga else "D" if gf == ga else "L", "pos": pos, "start": True,
           "min": 90, "rt": 7.0}
    row.update(stats)
    return row


def _logs_for_round() -> tuple[dict, list[dict]]:
    """A round of two matches with 14 outfield players and two keepers, ratings spread so a shape is forced."""
    logs: dict[str, dict] = {}
    fixtures = [{"id": "1", "date": "2026-09-01T15:00:00Z", "round": 1, "stage": "league", "status": "finished"},
                {"id": "2", "date": "2026-09-01T17:30:00Z", "round": 1, "stage": "league", "status": "finished"}]

    def add(pid, name, team, opp, ha, gf, ga, pos, gid="1", **stats):
        logs[pid] = {"name": name, "team": team, "pos": pos, "matches": [_row(gid, team, opp, ha, gf, ga, pos, **stats)]}

    # Home beat Away 3-1; keepers, five defenders, five midfielders, three forwards.
    add("g1", "Keeper A", "Home", "Away", "H", 3, 1, "G", rt=7.4, sv=4, gp=0.9)
    add("g2", "Keeper B", "Away", "Home", "A", 1, 3, "G", rt=6.2, sv=6, gp=-0.5)
    for i, rt in enumerate((8.0, 7.9, 7.8, 7.7, 6.0)):
        add(f"d{i}", f"Def {i}", "Home", "Away", "H", 3, 1, "D", rt=rt, tw=3, int=2, rec=4 + i)
    for i, rt in enumerate((8.4, 8.3, 7.0, 6.9, 6.8)):
        add(f"m{i}", f"Mid {i}", "Home", "Away", "H", 3, 1, "M", rt=rt, km=11.0 + i, kp=2, xa=0.35 if i == 0 else 0.1)
    add("f0", "Striker", "Home", "Away", "H", 3, 1, "F", rt=9.1, g=2, a=1, xg=0.9, xa=0.2, km=9.5)
    add("f1", "Winger", "Away", "Home", "A", 1, 3, "F", rt=7.5, g=1, xg=0.05)
    add("f2", "Sub", "Home", "Away", "H", 3, 1, "F", rt=9.9, min=20, g=1, xg=0.2)      # under 45': never in the XI
    add("f3", "Late sub", "Away", "Home", "A", 1, 3, "F", rt=9.5, min=50, g=1, a=1, xg=0.4)   # 50': XI yes, player of the week no
    return logs, fixtures


def _by_team() -> dict:
    """Two matches with a team sheet each side: Home beat Away 3-1 on a 2.4 v 0.6 xG; Third drew 0-0 with Fourth."""
    home = {"gid": "1", "date": "2026-09-01T15:00:00Z", "round": 1, "stage": "league", "opp": "Away", "ha": "H", "gf": 3, "ga": 1, "res": "W",
            "xg": 2.4, "xga": 0.6, "poss": 60, "box_touches": 30, "passes": 600, "passes_acc": 540, "tackles": 10, "interceptions": 5, "fouls": 5,
            "shots": 16, "sot": 8, "shots_ag": 6, "big_chances": 4, "big_chances_missed": 1, "corners": 7, "aerial_won": 10, "aerial_total": 20,
            "ground_won": 30, "ground_total": 50, "long_balls_att": 60, "crosses_att": 20, "dribbles": 8, "yellow": 2, "red": 0, "km": 110.0,
            "sprints": 120, "rating": 7.3, "has_sheet": True}
    away = {"gid": "1", "date": "2026-09-01T15:00:00Z", "round": 1, "stage": "league", "opp": "Home", "ha": "A", "gf": 1, "ga": 3, "res": "L",
            "xg": 0.6, "xga": 2.4, "poss": 40, "box_touches": 10, "passes": 400, "passes_acc": 300, "tackles": 20, "interceptions": 10, "fouls": 10,
            "shots": 6, "sot": 2, "shots_ag": 16, "big_chances": 1, "big_chances_missed": 1, "corners": 2, "aerial_won": 10, "aerial_total": 20,
            "ground_won": 20, "ground_total": 50, "long_balls_att": 80, "crosses_att": 10, "dribbles": 4, "yellow": 3, "red": 1, "km": 105.0,
            "sprints": 100, "rating": 6.6, "has_sheet": True}
    third = {"gid": "2", "date": "2026-09-01T17:30:00Z", "round": 1, "stage": "league", "opp": "Fourth", "ha": "H", "gf": 0, "ga": 0, "res": "D",
             "xg": 1.0, "xga": 1.0, "poss": 50, "box_touches": 20, "passes": 500, "passes_acc": 400, "tackles": 15, "interceptions": 5, "fouls": 5,
             "shots": 10, "sot": 3, "shots_ag": 10, "has_sheet": True}
    fourth = {**third, "opp": "Third", "ha": "A", "yellow": 0}
    return {"Home": [home], "Away": [away], "Third": [third], "Fourth": [fourth]}


# ── the formation optimiser ──────────────────────────────────────────────────

def test_formation_optimiser_picks_the_shape_with_the_highest_total_and_orders_the_eleven() -> None:
    cands = [_cand("G", 7.0), _cand("G", 6.0)]
    cands += [_cand("D", s) for s in (8.0, 7.9, 7.8, 7.7, 6.0)]
    cands += [_cand("M", s) for s in (8.4, 8.3, 7.0, 6.9, 6.8)]
    cands += [_cand("F", s) for s in (9.1, 7.5, 6.5)]
    formation, xi, bench = ins.pick_formation(cands)
    # 4 defenders (31.4), then the best of 3M+3F (8.4+8.3+7.0 + 9.1+7.5+6.5 = 46.8) v 4M+2F (30.6 + 16.6 = 47.2): 4-4-2 wins.
    assert formation == "4-4-2"
    assert [p["pos"] for p in xi] == ["G"] + ["D"] * 4 + ["M"] * 4 + ["F"] * 2
    assert xi[0]["rt"] == 7.0
    assert [p["rt"] for p in xi[1:5]] == [8.0, 7.9, 7.8, 7.7]
    assert [p["rt"] for p in xi[5:9]] == [8.4, 8.3, 7.0, 6.9]
    assert [p["rt"] for p in xi[9:]] == [9.1, 7.5]
    assert len(bench) == 3 and all(b["rt"] in (6.8, 6.5, 6.0) for b in bench)
    assert not {id(b) for b in bench} & {id(p) for p in xi}


def test_formation_optimiser_returns_what_there_is_without_a_shape() -> None:
    few = [_cand("G", 7.0)] + [_cand("D", 7.0, f"d{i}") for i in range(4)] + [_cand("M", 7.0, f"m{i}") for i in range(3)]
    formation, xi, bench = ins.pick_formation(few)
    assert formation is None and len(xi) == 8 and bench == []
    # Eleven players but no goalkeeper: the best eleven by rank, no formation.
    no_gk = [_cand("D", 7.0 + i / 10, f"d{i}") for i in range(6)] + [_cand("M", 7.0 + i / 10, f"m{i}") for i in range(6)]
    formation, xi, bench = ins.pick_formation(no_gk)
    assert formation is None and len(xi) == 11 and len(bench) == 1
    assert xi[0]["rt"] == pytest.approx(7.5)
    # A player without a position counts as a midfielder.
    shaped = [_cand("G", 7.0)] + [_cand("D", 7.0, f"d{i}") for i in range(4)] + [_cand("F", 7.0, f"f{i}") for i in range(3)]
    shaped += [{"pos": None, "score": 7.0, "key": (-7.0, f"x{i}"), "line": {"name": f"x{i}", "pos": None, "rt": 7.0}} for i in range(3)]
    formation, xi, _ = ins.pick_formation(shaped)
    assert formation == "4-3-3" and [p["pos"] for p in xi[5:8]] == [None, None, None]


# ── team and player of the week, awards ──────────────────────────────────────

def test_team_of_the_week_needs_45_minutes_and_ranks_by_rating_then_involvement() -> None:
    logs, fixtures = _logs_for_round()
    rounds = ins.build_rounds(fixtures, logs, {}, {}, None)
    assert len(rounds) == 1
    r = rounds[0]
    assert r["round"] == 1 and r["label"] == "Round 1" and r["matches"] == 2
    assert r["dates"] == ["2026-09-01T15:00:00Z", "2026-09-01T17:30:00Z"]
    totw = r["team_of_week"]
    assert totw["formation"] is not None and len(totw["xi"]) == 11
    names = [p["name"] for p in totw["xi"]]
    assert "Sub" not in names                                       # 20 minutes
    assert names[0] == "Keeper A" and totw["xi"][0]["pos"] == "G"
    assert "Late sub" in names and "Striker" in names
    assert set(totw["xi"][0]) == PLAYER_LINE
    assert 1 <= len(totw["bench"]) <= 3 and not {p["id"] for p in totw["bench"]} & {p["id"] for p in totw["xi"]}
    # Each line within a position is in descending rating.
    for pos in ("D", "M", "F"):
        rts = [p["rt"] for p in totw["xi"] if p["pos"] == pos]
        assert rts == sorted(rts, reverse=True)


def test_player_of_the_week_needs_60_minutes_and_explains_itself() -> None:
    logs, fixtures = _logs_for_round()
    potw = ins.build_rounds(fixtures, logs, {}, {}, None)[0]["player_of_week"]
    # The 9.9 sub (20') and the 9.5 late sub (50') are out; the 9.1 striker is in.
    assert potw["name"] == "Striker" and potw["rt"] == 9.1
    assert potw["why"] == "9.1 rating, two goals and an assist in a 3-1 win at home to Away"
    assert set(potw) == PLAYER_LINE | {"why"}
    # A tie on rating breaks on goals + assists, then xG + xA.
    logs["m0"]["matches"][0]["rt"] = 9.1
    logs["m0"]["matches"][0]["g"] = 4                                 # four involvements beat the striker's three
    potw = ins.build_rounds(fixtures, logs, {}, {}, None)[0]["player_of_week"]
    assert potw["name"] == "Mid 0"
    assert potw["why"] == "9.1 rating, four goals in a 3-1 win at home to Away"
    logs["f0"]["matches"][0]["g"] = 3                                 # now four each: 5.2 xG + xA beats 0.35
    logs["f0"]["matches"][0]["xg"] = 5.0
    potw = ins.build_rounds(fixtures, logs, {}, {}, None)[0]["player_of_week"]
    assert potw["name"] == "Striker"
    # An away defeat reads as such; a keeper's line mentions saves.
    logs["g2"]["matches"][0]["rt"] = 9.6
    potw = ins.build_rounds(fixtures, logs, {}, {}, None)[0]["player_of_week"]
    assert potw["why"] == "9.6 rating, six saves in a 1-3 defeat at Home"


def test_awards_need_a_qualifier_and_carry_a_label_and_value() -> None:
    logs, fixtures = _logs_for_round()
    awards = ins.build_rounds(fixtures, logs, {}, {}, None)[0]["awards"]
    assert set(awards) == {"finisher", "creator", "wall", "engine", "ball_winner"}
    for a in awards.values():
        assert set(a) == PLAYER_LINE | {"value", "label"}
    assert awards["finisher"]["name"] == "Striker" and awards["finisher"]["value"] == pytest.approx(2 - 0.9) and awards["finisher"]["label"] == "Goals − xG"
    assert awards["wall"]["name"] == "Keeper A" and awards["wall"]["value"] == pytest.approx(0.9) and awards["wall"]["label"] == "Goals prevented"
    assert awards["engine"]["name"] == "Mid 4" and awards["engine"]["value"] == pytest.approx(15.0)
    assert awards["ball_winner"]["name"] == "Def 4" and awards["ball_winner"]["value"] == pytest.approx(3 + 2 + 8)
    # Nobody scored: no finisher. Keeper under 60': no wall. A keeper never wins the ball-winner award.
    for e in logs.values():
        e["matches"][0].pop("g", None)
    logs["g1"]["matches"][0]["min"] = 45
    logs["g2"]["matches"][0]["min"] = 45
    logs["g1"]["matches"][0]["rec"] = 40
    awards = ins.build_rounds(fixtures, logs, {}, {}, None)[0]["awards"]
    assert "finisher" not in awards and "wall" not in awards
    assert awards["ball_winner"]["name"] == "Def 4"
    assert awards["creator"]["name"] == "Mid 0"                       # no assists left; 0.35 xA still qualifies


def test_creator_is_max_xa_among_qualifiers() -> None:
    logs, fixtures = _logs_for_round()
    awards = ins.build_rounds(fixtures, logs, {}, {}, None)[0]["awards"]
    assert awards["creator"]["name"] == "Mid 0" and awards["creator"]["value"] == pytest.approx(0.35) and awards["creator"]["label"] == "xA"


# ── expected points ──────────────────────────────────────────────────────────

def test_expected_points_come_from_a_poisson_score_matrix() -> None:
    m = ins.poisson_score_matrix(1.5, 1.0)
    assert len(m) == 9 and all(len(r) == 9 for r in m)
    assert sum(map(sum, m)) == pytest.approx(1.0)
    even = ins.expected_points(1.2, 1.2)
    assert even["win"] == pytest.approx(even["loss"]) and even["xpts"] == pytest.approx(3 * even["win"] + even["draw"])
    assert even["win"] + even["draw"] + even["loss"] == pytest.approx(1.0)
    dominant = ins.expected_points(3.0, 0.2)
    assert dominant["xpts"] > 2.7 and dominant["win"] > 0.9
    assert ins.expected_points(0.0, 0.0)["draw"] == pytest.approx(1.0)
    assert ins.expected_points(None, 1.0) is None and ins.expected_points(1.0, "x") is None


def test_team_awards_read_both_rows_of_a_match() -> None:
    by_team = _by_team()
    awards = ins.team_awards({"1", "2"}, ins._team_rows_by_gid(by_team))
    assert set(awards) == {"best_xg_diff", "luckiest", "unluckiest"}          # Home's win had 80% of the xG: no smash and grab
    assert all(set(a) == TEAM_AWARD for a in awards.values())
    assert awards["best_xg_diff"]["team"] == "Home" and awards["best_xg_diff"]["value"] == pytest.approx(1.8)
    assert awards["unluckiest"]["team"] == "Away" and awards["unluckiest"]["value"] < 0
    # Flip the match: Away won 1-0 on 0.6 v 2.4 xG.
    by_team["Away"][0].update({"gf": 1, "ga": 0, "res": "W"})
    by_team["Home"][0].update({"gf": 0, "ga": 1, "res": "L"})
    awards = ins.team_awards({"1", "2"}, ins._team_rows_by_gid(by_team))
    assert awards["smash_and_grab"]["team"] == "Away" and awards["smash_and_grab"]["value"] == pytest.approx(0.2)
    assert awards["luckiest"]["team"] == "Away" and awards["unluckiest"]["team"] == "Home"
    assert awards["luckiest"]["gid"] == "1" and awards["luckiest"]["ha"] == "A"
    # The opponent's xG is read from the opponent's row when a row lacks xga.
    del by_team["Away"][0]["xga"]
    awards = ins.team_awards({"1"}, ins._team_rows_by_gid(by_team))
    assert awards["smash_and_grab"]["xga"] == pytest.approx(2.4)


# ── team metrics and percentiles ─────────────────────────────────────────────

def test_team_metrics_use_the_opponent_row_and_summed_ratios() -> None:
    by_team = _by_team()
    rows_by_gid = ins._team_rows_by_gid(by_team)
    opp_of = lambda r: next(o for t, o in rows_by_gid[r["gid"]].items() if t != "Home")  # noqa: E731
    v = ins.team_metric_values(by_team["Home"], opp_of)
    assert set(v) == {m["key"] for m in TEAM_METRICS}
    assert v["xg_for"] == 2.4 and v["xg_against"] == 0.6 and v["xg_diff"] == pytest.approx(1.8)
    assert v["finishing"] == pytest.approx(0.6) and v["keeping"] == pytest.approx(-0.4)
    assert v["field_tilt"] == pytest.approx(75.0)                    # 30 / (30 + 10)
    assert v["ppda"] == pytest.approx(400 / 20)                      # opponent passes / (10 + 5 + 5)
    assert v["shots_against"] == 6 and v["shot_quality"] == pytest.approx(2.4 / 16) and v["shot_quality_against"] == pytest.approx(0.1)
    assert v["sot_pct"] == pytest.approx(50.0) and v["aerial_pct"] == pytest.approx(50.0) and v["ground_duel_pct"] == pytest.approx(60.0)
    assert v["pass_pct"] == pytest.approx(90.0) and v["long_ball_share"] == pytest.approx(10.0)
    assert v["cards"] == 2 and v["crosses"] == 20
    xp = ins.expected_points(2.4, 0.6)["xpts"]
    assert v["xpts_per_match"] == pytest.approx(xp) and v["luck"] == pytest.approx(3 - xp)
    away = ins.team_metric_values(by_team["Away"], lambda r: by_team["Home"][0])
    assert away["cards"] == 5 and away["field_tilt"] == pytest.approx(25.0)
    # A row without a sheet still yields the xG-based metrics and nothing else.
    bare = ins.team_metric_values([{"gid": "9", "gf": 1, "ga": 1, "res": "D", "xg": 1.1, "xga": 0.9}], lambda r: None)
    assert bare["xg_diff"] == pytest.approx(0.2) and bare["possession"] is None and bare["ppda"] is None


def test_percentiles_are_direction_aware_and_span_0_to_100() -> None:
    vals = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "E": 4.0}
    hi = ins.percentile_ranks(vals, lower=False)
    assert hi["A"] == 0 and hi["D"] == hi["E"] == 88 and hi["B"] == 25
    lo = ins.percentile_ranks(vals, lower=True)
    assert lo["A"] == 100 and lo["D"] == lo["E"] == 12
    assert ins.percentile_ranks({"only": 1.0}) == {}
    assert ins.percentile_ranks({"a": 1.0, "b": 2.0}) == {"a": 0, "b": 100}


def test_team_profiles_rank_every_team_best_first() -> None:
    teams, perf = ins.team_profiles(_by_team())
    assert set(teams) == {"Home", "Away", "Third", "Fourth"}
    assert teams["Home"]["played"] == 1
    assert teams["Home"]["profile"]["xg_diff"] == {"v": 1.8, "pct": 100}
    assert teams["Away"]["profile"]["xg_against"]["pct"] == 0 and teams["Home"]["profile"]["xg_against"]["pct"] == 100
    form = teams["Home"]["form"][0]
    assert set(form) == {"gid", "date", "opp", "ha", "gf", "ga", "res", "xg", "xga", "xpts", "pts"} and form["pts"] == 3
    assert teams["Home"]["rounds"] == [{"round": 1, "pts": 3, "xpts": form["xpts"], "xg": 2.4, "xga": 0.6}]
    ranking = perf["ppda"]["ranking"]
    assert perf["ppda"]["lower"] is True and ranking[0]["team"] == "Away" and ranking[0]["pct"] == 100
    assert [r["team"] for r in perf["xg_for"]["ranking"]] == ["Home", "Third", "Fourth", "Away"] or \
           [r["team"] for r in perf["xg_for"]["ranking"]] == ["Home", "Fourth", "Third", "Away"]
    assert all(len(perf[k]["ranking"]) == 4 for k in ("xg_for", "luck"))
    assert len(perf["possession"]["ranking"]) == 4 and len(perf["cards"]["ranking"]) == 3     # Third has no card count


# ── season XIs and performers ────────────────────────────────────────────────

def _players() -> list[dict]:
    out = []
    n = 0
    for pos, count in (("G", 2), ("D", 6), ("M", 6), ("F", 4)):
        for i in range(count):
            n += 1
            gk = pos == "G"
            out.append({"player_id": str(n), "name": f"{pos}{i}", "team": "Home" if n % 2 else "Away", "position": pos, "is_gk": gk,
                        "minutes": 900 - 10 * n, "goals": i, "assists": 1, "xg": 0.5 * i, "xa": 0.3, "rating": 7.0 + n / 20,
                        "qualified": True, "pct": {"rating": 5 * n},
                        "npxg_xa_90": None if gk else 0.1 * n, "goals_prevented_90": 0.2 if gk else None,
                        "padj_tkl_int_90": 4.0 - n / 10, "ball_wins_90": 5.0, "def_actions_90": 2.0,
                        "loss_per_100": 10.0 + n, "save_pct": 70.0 if gk else None})
    out[-1]["qualified"] = False                       # under the floor: never listed
    return out


def test_season_xis_use_the_basis_and_carry_season_totals() -> None:
    players = _players()
    xis = ins.season_xis(players, {}, 270)
    assert set(xis) == {"rating", "output", "defence", "form"}
    rating = xis["rating"]
    assert rating["formation"] and len(rating["xi"]) == 11 and rating["basis"] == "minutes-weighted rating"
    top = rating["xi"][0]
    assert set(top) == PLAYER_LINE | {"value"} and top["pos"] == "G" and top["rt"] == top["value"]
    assert top["gid"] is None and top["min"] > 0
    assert "F3" not in {p["name"] for p in rating["xi"]}             # not qualified
    out = xis["output"]
    assert out["xi"][0]["pos"] == "G" and out["xi"][0]["value"] == 0.2
    assert all(p["value"] == pytest.approx(0.1 * int(p["id"])) for p in out["xi"][1:])
    # Form needs logs with three rated matches; none here.
    assert xis["form"]["formation"] is None and xis["form"]["xi"] == []
    logs = {p["player_id"]: {"name": p["name"], "team": p["team"], "pos": p["position"],
                             "matches": [{"gid": str(k), "min": 90, "rt": 6.0 + k} for k in range(7)]} for p in players}
    form = ins.season_xis(players, logs, 270)["form"]
    assert form["formation"] and len(form["xi"]) == 11
    assert form["xi"][0]["value"] == pytest.approx((6 + 7 + 8 + 9 + 10) / 5)   # the last five, rows newest first


def test_player_performers_are_scoped_and_reversed_for_lower_is_better() -> None:
    perf = ins.player_performers(_players(), 270)
    assert set(perf) == set(ins.PERFORMER_KEYS)
    rating = perf["rating"]
    assert rating["scope"] == "out" and rating["lower"] is False and rating["label"] == "Rating"
    assert len(rating["top"]) == 8 and len(rating["bottom"]) == 8
    assert rating["top"][0]["value"] > rating["top"][-1]["value"] >= rating["bottom"][-1]["value"] > rating["bottom"][0]["value"]
    assert set(rating["top"][0]) == {"id", "name", "team", "pos", "value", "minutes", "pct"}
    assert rating["top"][0]["pct"] == 5 * int(rating["top"][0]["id"])
    assert all(p["pos"] != "G" for p in rating["top"] + rating["bottom"])
    gk = perf["goals_prevented_90"]
    assert gk["scope"] == "gk" and all(p["pos"] == "G" for p in gk["top"]) and len(gk["top"]) == 2
    loss = perf["loss_per_100"]
    assert loss["lower"] is True and loss["top"][0]["value"] < loss["top"][1]["value"]
    assert loss["bottom"][0]["value"] > loss["bottom"][1]["value"]
    assert perf["save_pct"]["top"][0]["pct"] is None                  # no percentile for that key


# ── the payload and its degradation ──────────────────────────────────────────

def test_build_analytics_has_the_contract_shape() -> None:
    logs, fixtures = _logs_for_round()
    players = _players()
    payload = ins.build_analytics(players, logs, _by_team(), fixtures, floor=270, season="Test 26/27", round_labels={"final": "Final"})
    assert set(payload) == TOP_KEYS
    assert payload["season"] == "Test 26/27" and payload["minutes_floor"] == 270
    assert payload["team_metrics"] == TEAM_METRICS
    assert payload["player_metrics"] == ins.PERFORMER_KEYS
    assert len(payload["rounds"]) == 1 and set(payload["rounds"][0]) >= {"round", "label", "dates", "matches", "team_of_week", "player_of_week", "awards", "team_awards"}
    assert set(payload["performers"]) == {"players", "teams"}
    assert set(payload["teams"]) == {"Home", "Away", "Third", "Fourth"}
    # Knockout rounds take the label map, newest first; qualifying rounds are skipped.
    fixtures += [{"id": "7", "date": "2026-10-10T20:00:00Z", "round": "final", "stage": "playoff", "status": "finished"},
                 {"id": "8", "date": "2026-07-10T20:00:00Z", "round": 1, "stage": "qualifying", "status": "finished"},
                 {"id": "9", "date": "2026-12-10T20:00:00Z", "round": 2, "stage": "league", "status": "scheduled"}]
    logs["f0"]["matches"].append(_row("7", "Home", "Away", "H", 1, 0, "F", rt=8.0))
    logs["f0"]["matches"][-1]["round"] = "final"
    logs["f0"]["matches"][-1]["date"] = "2026-10-10T20:00:00Z"
    payload = ins.build_analytics(players, logs, _by_team(), fixtures, floor=270, round_labels={"final": "Final"})
    assert [(r["round"], r["label"]) for r in payload["rounds"]] == [("final", "Final"), (1, "Round 1")]
    assert payload["rounds"][0]["team_of_week"]["formation"] is None and len(payload["rounds"][0]["team_of_week"]["xi"]) == 1


def test_everything_degrades_on_empty_input() -> None:
    for args in (([], {}, {}, []), (None, None, None, None)):
        payload = ins.build_analytics(*args)
        assert set(payload) == TOP_KEYS
        assert payload["rounds"] == [] and payload["teams"] == {}
        assert payload["performers"]["teams"] == {}
        assert all(xi["xi"] == [] and xi["formation"] is None for xi in payload["season_xi"].values())
        assert payload["minutes_floor"] == 0 and payload["season"] is None
    # Malformed rows are skipped, not fatal.
    payload = ins.build_analytics([{"bad": 1}], {"x": 3}, {"T": [None, 4]}, [None, {"id": "1"}])
    assert set(payload) == TOP_KEYS and payload["rounds"] == [] and payload["teams"]["T"]["played"] == 0
    assert all(xi["xi"] == [] for xi in payload["season_xi"].values())
    # Players without logs: performers and season XIs, no rounds. Logs without sheets: rounds with player awards only.
    p = ins.build_analytics(_players(), {}, {}, [], floor=270)
    assert p["rounds"] == [] and p["performers"]["players"]["rating"]["top"] and p["season_xi"]["rating"]["xi"]
    logs, fixtures = _logs_for_round()
    p = ins.build_analytics([], logs, {}, fixtures)
    assert p["rounds"][0]["team_awards"] == {} and p["rounds"][0]["awards"]["finisher"]["name"] == "Striker"
    assert p["performers"]["players"]["rating"]["top"] == [] and p["teams"] == {}
    # Every number in the payload is JSON-clean.
    import json
    json.dumps(p)


def test_matches_without_a_round_group_by_calendar_week() -> None:
    from oddsmarkets.football.analytics.insights import _round_groups

    fx = [{"id": 1, "status": "finished", "stage": "league", "round": None, "date": "2026-09-19T19:00:00Z"},   # Sat, ISO week 38
          {"id": 2, "status": "finished", "stage": "league", "round": None, "date": "2026-09-20T15:00:00Z"},   # Sun, week 38
          {"id": 3, "status": "finished", "stage": "league", "round": None, "date": "2026-09-26T19:00:00Z"},   # week 39
          {"id": 4, "status": "finished", "stage": "league", "round": 5, "date": "2026-09-27T15:00:00Z"},
          {"id": 5, "status": "finished", "stage": "league", "round": None, "date": None}]
    groups = _round_groups(fx, None)
    assert [g["label"] for g in groups] == ["Round 5", "Week of 21 Sep", "Week of 14 Sep"]
    assert groups[2]["gids"] == {"1", "2"} and groups[1]["round"] == "w2026-39"
