"""Pro Football Reference data is left out (sports-reference.com/data_use): no PFR release is fetched, PFR-origin
columns are scrubbed from the mirror and the stores, pre-2008 draft slots are not published, and on-field snap shares
come from the play-by-play participation instead of nflverse snap counts."""
from __future__ import annotations

import pandas as pd
import pytest

from oddsmarkets.nfl import store as st
from oddsmarkets.nfl.sources import nflverse


def test_pfr_releases_not_fetchable():
    for rel in ("snap_counts", "pfr_advstats", "trades", "draft_picks", "combine"):
        assert rel in nflverse.LEFT_OUT
        assert rel not in nflverse.RELEASES
        with pytest.raises(ValueError):
            nflverse.fetch_file(rel, "x.parquet")


def test_scrub_players_schedules_rosters(tmp_path):
    pl = pd.DataFrame({"gsis_id": ["00-1", "00-2", "00-3"], "pfr_id": ["A", "B", None],
                       "draft_year": [2005.0, 2010.0, None], "draft_round": [1.0, 2.0, None],
                       "draft_pick": [1.0, 40.0, None], "draft_team": ["SF", "KC", None]})
    p = tmp_path / "players.parquet"
    pl.to_parquet(p, index=False)
    assert nflverse.scrub_file("players", p)
    got = pd.read_parquet(p)
    assert "pfr_id" not in got.columns
    assert got.loc[0, ["draft_year", "draft_round", "draft_pick", "draft_team"]].isna().all()
    assert got.loc[1, "draft_year"] == 2010 and got.loc[1, "draft_pick"] == 40 and got.loc[1, "draft_team"] == "KC"
    assert not nflverse.scrub_file("players", p)                       # idempotent
    sc = tmp_path / "games.parquet"
    pd.DataFrame({"game_id": ["g"], "pfr": ["202409080buf"], "espn": ["1"]}).to_parquet(sc, index=False)
    assert nflverse.scrub_file("schedules", sc) and "pfr" not in pd.read_parquet(sc).columns
    ro = tmp_path / "roster.parquet"
    pd.DataFrame({"gsis_id": ["00-1"], "pfr_id": ["A"], "team": ["SF"]}).to_parquet(ro, index=False)
    assert nflverse.scrub_file("weekly_rosters", ro) and "pfr_id" not in pd.read_parquet(ro).columns


def test_compact_game_has_no_pfr_id(schedules):
    g = nflverse.compact_game(schedules.iloc[0].to_dict())
    assert "pfr_id" not in g and g.get("espn_id") is not None


def test_store_scrubs_pfr_id(gridiron_roots):
    s = st.new_store(2024)
    s["games"]["g1"] = {"game_id": "g1", "season": 2024, "pfr_id": "202409080buf", "espn_id": "1"}
    st.write_json(st.season_path(2024), s)                             # an older store, written without save()
    assert "pfr_id" not in st.load(2024)["games"]["g1"]
    st.save(s)
    assert "pfr_id" not in st.read_json(st.season_path(2024))["games"]["g1"]


def test_people_drop_pre_2008_draft(gridiron_roots):
    from oddsmarkets.nfl.analytics import people
    d = gridiron_roots["raw"] / "raw" / "players"
    d.mkdir(parents=True)
    pd.DataFrame({"gsis_id": ["00-0000001", "00-0000002", "00-0000003"], "display_name": ["Old", "New", "Undrafted"],
                  "position": ["QB", "WR", "RB"], "draft_year": [2000.0, 2012.0, None], "draft_round": [6.0, 1.0, None],
                  "draft_pick": [199.0, 3.0, None], "draft_team": ["NE", "CLE", None]}).to_parquet(d / "players.parquet")
    people.reset()
    try:
        ppl = people.people()
        assert ppl["00-0000001"]["draft"] is None
        assert ppl["00-0000002"]["draft"] == {"year": 2012, "round": 1, "pick": 3, "team": "CLE"}
        assert ppl["00-0000003"]["draft"] is None
    finally:
        people.reset()


def _plays(season_dir):
    off_a = ";".join(f"00-A{i:02d}" for i in range(11))
    off_a2 = ";".join(f"00-A{i:02d}" for i in range(10)) + ";00-A99"
    def_b = ";".join(f"00-B{i:02d}" for i in range(11))
    rows = []
    for k in range(10):                                   # A on offence: A00..A09 every play, A10 on 6, A99 on 4
        rows.append({"game_id": "2024_01_AAA_BBB", "week": 1, "play_type": "pass" if k % 2 else "run", "posteam": "KC",
                     "defteam": "BUF", "part_offense_players": off_a if k < 6 else off_a2, "part_defense_players": def_b})
    rows.append({"game_id": "2024_01_AAA_BBB", "week": 1, "play_type": "punt", "posteam": "KC", "defteam": "BUF",
                 "part_offense_players": off_a, "part_defense_players": def_b})          # special teams: not a snap
    season_dir.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(season_dir / "plays.parquet", index=False)


def test_onfield_and_continuity_from_participation(gridiron_roots):
    from oddsmarkets.nfl.models import _cdata as D
    from oddsmarkets.nfl.models import team_strength as TS
    raw = gridiron_roots["raw"]
    _plays(raw / "derived" / "2024")
    O = D.onfield(2024)
    off = O[(O["side"] == "off") & (O["team"] == "KC")].set_index("player")
    assert off.loc["00-A00", "snaps"] == 10 and off.loc["00-A10", "snaps"] == 6 and off.loc["00-A99", "snaps"] == 4
    assert (off["team_snaps"] == 10).all()
    assert D.onfield(2023) is None
    # 2025 opening roster: A00..A04 still at KC, A05 cut, the rest gone elsewhere; BUF keeps every defender
    wr = raw / "raw" / "weekly_rosters"
    wr.mkdir(parents=True)
    ros = [{"week": 1, "game_type": "REG", "team": "KC", "gsis_id": f"00-A{i:02d}", "status": "ACT"} for i in range(5)]
    ros += [{"week": 1, "game_type": "REG", "team": "KC", "gsis_id": "00-A05", "status": "CUT"}]
    ros += [{"week": 1, "game_type": "REG", "team": "BUF", "gsis_id": f"00-B{i:02d}", "status": "ACT"} for i in range(11)]
    ros += [{"week": 2, "game_type": "REG", "team": "KC", "gsis_id": "00-A06", "status": "ACT"}]   # later week: ignored
    ros += [{"week": 2, "game_type": "REG", "team": "MIA", "gsis_id": "00-M01", "status": "ACT"}]  # club first listed in week 2
    pd.DataFrame(ros).to_parquet(wr / "roster_weekly_2025.parquet", index=False)
    start = D.roster_at_start(2025)
    assert start["00-M01"] == "MIA" and "00-A06" not in start and "00-A05" not in start
    c = TS.continuity(2025)
    assert c["KC"]["off"] == pytest.approx(50 / 110)
    assert c["BUF"]["def"] == pytest.approx(1.0)
    assert TS.continuity(2024) == {}                      # no 2023 participation on disk
