"""The announced MLB award winners (Stats API recipients, cached) and how they land on award_history.json."""
from datetime import date

from oddsmarkets.baseball.analytics import award_history as AH
from oddsmarkets.baseball.analytics import mlbapi


class FakeClient:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def get(self, url, params=None):
        self.calls.append(url)
        aid = url.split("/awards/")[1].split("/")[0]
        if aid not in self.answers:
            return {"awards": []}
        pid, name = self.answers[aid]
        return {"awards": [{"id": aid, "date": "2026-11-12", "season": "2026", "player": {"id": pid, "nameFirstLast": name}}]}


def test_award_winners_caches_and_is_final_once_all_six_are_in(tmp_path, monkeypatch):
    monkeypatch.setenv("BULLPEN_CACHE", str(tmp_path))
    first = FakeClient({"ALMVP": (670541, "Yordan Alvarez"), "ALROY": (805808, "Kevin McGonigle")})
    got = mlbapi.award_winners(2026, first, today=date(2026, 11, 12))
    assert got["al_mvp"] == {"pid": "670541", "name": "Yordan Alvarez", "date": "2026-11-12"}
    assert set(got) == {"al_mvp", "al_roy"} and len(first.calls) == 6
    # within max_age_h: the cache answers, no calls
    again = FakeClient({})
    assert set(mlbapi.award_winners(2026, again, today=date(2026, 11, 12))) == {"al_mvp", "al_roy"} and not again.calls
    # stale: only the missing four are asked for; then all six are in and the cache is final
    full = FakeClient({k: (i, f"P{i}") for i, k in enumerate(["NLMVP", "ALCY", "NLCY", "NLROY"], start=1)})
    got = mlbapi.award_winners(2026, full, max_age_h=0, today=date(2026, 11, 13))
    assert len(got) == 6 and len(full.calls) == 4
    done = FakeClient({})
    assert len(mlbapi.award_winners(2026, done, max_age_h=0, today=date(2026, 11, 20))) == 6 and not done.calls


def test_award_winners_offline_and_before_october_make_no_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("BULLPEN_CACHE", str(tmp_path))
    c = FakeClient({"ALMVP": (1, "X")})
    assert mlbapi.award_winners(2026, c, today=date(2026, 9, 20)) == {} and not c.calls
    assert mlbapi.award_winners(2026, None, today=date(2026, 11, 20)) == {}


def test_award_history_carries_the_announced_winner():
    cur = {"awards": {"al_mvp": {"rows": [{"pid": "670541", "name": "Yordan Alvarez", "p": 0.95}, {"pid": "1", "name": "Other", "p": 0.05}],
                                 "winner": {"pid": "670541", "name": "Yordan Alvarez", "p": 0.95, "rank": 1}},
                      "nl_mvp": {"rows": [{"pid": "2", "name": "A", "p": 0.6}, {"pid": "3", "name": "B", "p": 0.4}]}}}
    h = AH.build(2099, cur, True)
    if h is None:            # no committed walk-forward calls in this checkout
        return
    s = h["seasons"]["2099"]
    assert s["al_mvp"]["winner"] == {"pid": "670541", "name": "Yordan Alvarez", "p": 0.95, "rank": 1}
    assert s["nl_mvp"]["winner"] is None
