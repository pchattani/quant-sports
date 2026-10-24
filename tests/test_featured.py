"""The significance rule that picks the game a page leads with (oddsmarkets/common/featured.py)."""
from datetime import datetime, timedelta, timezone

from oddsmarkets.common import featured as F

NOW = datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)   # Fri 22:00 in New York, Sat 03:00 in London


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def g(sport, league, start, p_home=0.5, status="pre", gid="1", **sig):
    out = {"sport": sport, "league": league, "id": gid, "start": iso(start), "status": status, "p_home": p_home}
    if sig:
        out["sig"] = sig
    return out


def wta250_3am():
    # the user's screenshot: Bouzkova v Fernandez, WTA Ningbo (a 250), 50/50, 03:00 in New York = 07:00 UTC
    return g("tennis", "WTA · Ningbo", NOW.replace(hour=7), 0.5, gid="wta", comp="250", round="R16")


def test_wta_250_at_3am_loses_to_nfl_same_day():
    nfl = g("nfl", "NFL", NOW.replace(hour=17), 0.62, gid="nfl")         # Sat 13:00 in New York
    nfl["start"] = iso(NOW.replace(hour=17) + timedelta(days=0))
    a, b = F.significance(wta250_3am(), NOW), F.significance(nfl, NOW)
    assert b["score"] > a["score"] + 20, (a, b)
    top = F.rank_featured([wta250_3am(), nfl], NOW)["today"]
    assert top and top[0]["key"] == "nfl:nfl"
    assert all(r["key"] != "tennis:wta" for r in top)                  # below the bar: never leads the page


def test_wta_250_at_3am_loses_to_epl_same_day():
    epl = g("football", "Premier League", NOW.replace(hour=14), 0.45, gid="epl", comp="premier-league")
    epl["p_draw"], epl["p_away"] = 0.27, 0.28
    top = F.rank_featured([wta250_3am(), epl], NOW)["today"]
    assert top[0]["key"] == "football:epl"


def test_hour_rule_and_closeness_is_small():
    early = F.significance(wta250_3am(), NOW)
    assert early["parts"]["hour"] == -18                               # 02:00 New York, 08:00 Paris
    assert early["parts"]["close"] <= 6
    late_ok = g("tennis", "WTA", NOW.replace(hour=3), comp="250")      # 23:00 New York: a sane hour
    assert F.significance(late_ok, NOW)["parts"]["hour"] == 0
    # a lopsided NFL game still beats a dead-even WTA 250 at a good hour
    lop = g("nfl", "NFL", NOW.replace(hour=17), 0.85, gid="n2")
    even = g("tennis", "WTA", NOW.replace(hour=15), 0.5, gid="t2", comp="250")
    assert F.significance(lop, NOW)["score"] > F.significance(even, NOW)["score"]


def test_stage_and_stakes_lift_a_game():
    base = g("baseball", "MLB", NOW + timedelta(hours=16), 0.55, gid="a")
    g7 = g("baseball", "MLB", NOW + timedelta(hours=16), 0.55, gid="b",
           series={"game": 7, "wins": [3, 3], "best_of": 7, "name": "AL Championship Series"})
    assert F.significance(g7, NOW)["score"] > F.significance(base, NOW)["score"] + 25
    title = g("football", "Premier League", NOW + timedelta(hours=12), 0.4, gid="c", comp="premier-league",
              title=[0.45, 0.5])
    plain = g("football", "Premier League", NOW + timedelta(hours=12), 0.4, gid="d", comp="premier-league",
              title=[0.0, 0.0])
    s = F.significance(title, NOW)
    assert s["score"] > F.significance(plain, NOW)["score"] + 15
    assert "two title contenders" in s["reasons"]
    pre = g("basketball", "NBA", NOW + timedelta(hours=17), 0.5, gid="e", preseason=True)
    assert F.significance(pre, NOW)["parts"]["tier"] < 20


def test_live_first_then_soon_and_fallback_week():
    live = g("hockey", "NHL", NOW - timedelta(hours=1), 0.5, status="live", gid="l")
    soon = g("hockey", "NHL", NOW + timedelta(hours=16), 0.5, gid="s")
    r = F.rank_featured([soon, live], NOW)["today"]
    assert [x["key"] for x in r] == ["hockey:l", "hockey:s"]
    # nothing big today: `today` is empty, `week` names Sunday's Grand Prix
    gp = {"sport": "f1", "league": "Formula 1", "id": "gp", "start": iso(NOW + timedelta(days=2)), "status": "pre",
          "event": True}
    r = F.rank_featured([wta250_3am(), gp], NOW)
    assert r["today"] == [] and r["week"]["key"] == "f1:gp"
    # finished and stale games never lead
    done = g("nfl", "NFL", NOW - timedelta(hours=5), status="final", gid="f")
    stale = g("nfl", "NFL", NOW - timedelta(hours=30), gid="x")
    assert F.rank_featured([done, stale], NOW) == {"today": [], "week": None}


def test_when_label_never_says_our_pick():
    ny = -4 * 60                                                       # New York in October (EDT)
    assert F.when_label(iso(NOW.replace(hour=7)), NOW, ny) == "Tomorrow · 03:00"   # it is 22:00 Fri there
    assert F.when_label(iso(NOW + timedelta(hours=1)), NOW, ny) == "Tonight · 23:00"
    assert F.when_label(iso(NOW.replace(hour=17)), NOW, ny) == "Tomorrow · 13:00"
    assert F.when_label(iso(NOW + timedelta(days=2)), NOW, 0) == "Mon · 02:00"
    assert F.when_label(iso(NOW + timedelta(hours=11)), NOW, 0) == "Today · 13:00"
    assert F.when_label(iso(NOW), NOW, 0, live=True) == "Live now"


def test_a_conference_title_game_outranks_a_plain_ranked_game():
    """stage "conf_final" (a college conference title game) adds stage points and says why."""
    from datetime import datetime, timezone
    now = datetime(2026, 12, 5, 12, tzinfo=timezone.utc)
    base = {"sport": "college", "league": "CFB", "start": "2026-12-05T21:00:00Z", "status": "pre", "p_home": 0.6}
    conf = F.significance(dict(base, id="1", sig={"stage": "conf_final", "ranks": [8, 15]}), now)
    reg = F.significance(dict(base, id="2", sig={"ranks": [8, 15]}), now)
    assert conf["score"] > reg["score"] and "a conference title game" in conf["reasons"]
