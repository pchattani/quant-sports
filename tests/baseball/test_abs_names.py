"""ABS challenge tables carry names: the challenger's id resolved from the play text, and the season tables' names."""
import numpy as np
import pandas as pd

from oddsmarkets.baseball.analytics import games as GM
from oddsmarkets.baseball.analytics import umpires as UM
from oddsmarkets.baseball.models import umpire as U

NAMES = {"1": "Matt Olson", "2": "Zack Wheeler", "3": "J.T. Realmuto", "4": "José Ramírez"}


class Ctx:
    teams = {"144": {"name": "Atlanta Braves", "abbr": "ATL"}, "143": {"name": "Philadelphia Phillies", "abbr": "PHI"}}

    def name(self, pid):
        return NAMES.get(str(pid), str(pid))

    def tid(self, abbr):
        return {"ATL": "144", "PHI": "143"}.get(str(abbr).upper())


def folded(pid):
    return U._c_name(NAMES.get(str(pid)))


def test_resolve_challenger_roles():
    assert U.resolve_challenger("matt olson", 1, 2, 3, None, folded) == ("batter", "1")
    assert U.resolve_challenger("zack wheeler", 1, 2, 3, None, folded) == ("pitcher", "2")
    assert U.resolve_challenger("jt realmuto", 1, 2, 3, None, folded) == ("catcher", "3")
    # a batter whose stored name differs is found by the play text, which starts with the batter
    assert U.resolve_challenger("ji hwan bae", 9, 2, 3, "ji hwan bae strikes out", folded) == ("batter", "9")
    assert U.resolve_challenger("jose ramirez", 4, 2, np.nan, None, folded) == ("batter", "4")
    assert U.resolve_challenger(None, 1, 2, 3, None, folded) == ("unknown", None)
    assert U.resolve_challenger("someone", 1, 2, np.nan, None, folded) == ("unknown", None)


def test_named_abs_adds_names_and_team_ids():
    abs_ = {"ok": True, "n": 3,
            "challengers": {"cols": ["challenger", "role", "n", "won", "runs", "rate", "runs_per"],
                            "rows": [["3", "catcher", 3, 2, 0.8, 0.667, 0.27], ["77", "batter", 3, 0, 0.0, 0.0, 0.0]]},
            "best": {"cols": ["challenger", "role", "n"], "rows": [["3", "catcher", 3]]},
            "teams": {"cols": ["team", "n", "won", "runs", "rate"], "rows": [["PHI", 3, 2, 0.8, 0.667], ["XYZ", 1, 0, 0, 0]]},
            "umpires": {"cols": ["ump", "n", "overturned", "rate"], "rows": [["504381", 3, 2, 0.667]]}}
    out = UM.named_abs(Ctx(), abs_, {"504381": {"name": "Will Little"}})
    ch = out["challengers"]
    assert ch["cols"][-1] == "name" and ch["rows"][0][-1] == "J.T. Realmuto" and ch["rows"][1][-1] is None   # never the bare id
    assert out["best"]["rows"][0][-1] == "J.T. Realmuto"
    assert out["teams"]["cols"][-1] == "tid" and out["teams"]["rows"][0][-1] == "143" and out["teams"]["rows"][1][-1] is None
    assert out["umpires"]["rows"][0][-1] == "Will Little"
    assert "name" not in abs_["challengers"]["cols"]                       # the model's dict is not changed
    assert UM.named_abs(Ctx(), out, {})["challengers"]["cols"].count("name") == 1   # idempotent


def test_game_abs_carries_challenger_id_role_and_team():
    gp = pd.DataFrame({
        "inning": [10, 10, 8], "inning_topbot": ["Bot", "Bot", "Top"], "at_bat_number": [83, 87, 70], "pitch_number": [6, 3, 2],
        "batter": [1, 5, 1], "pitcher": [2, 2, 2], "fielder_2": [3, 3, 6],
        "des": ["Matt Olson challenged (pitch result), call on the field was confirmed: Matt Olson strikes out swinging.",
                "J.T. Realmuto challenged (pitch result), call on the field was overturned: Ozzie Albies strikes out.",
                "Braves challenged (trap play), call on the field was upheld: Bryce Harper lines out."]})
    g = {"home": "144", "away": "143"}
    out = GM._abs(Ctx(), gp, g)
    olson, realmuto, review = out
    assert (olson["by"], olson["role"], olson["name"], olson["team"]) == ("1", "batter", "Matt Olson", "144")
    assert (realmuto["by"], realmuto["role"], realmuto["name"], realmuto["team"]) == ("3", "catcher", "J.T. Realmuto", "143")
    assert review["role"] == "review" and review["by"] is None and review["team"] == "144" and review["name"] == "Braves"
