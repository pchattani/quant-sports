"""The Quant Scrum's site-wide payloads: index.json (scopes, teams, freshness), search.json and glossary.json."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import build as B, config

GLOSSARY = [
    ("Our rating", "Points better than an average test side on a neutral ground: +10 means a side expected to beat an "
     "average test team by ten. Built from every result, with home advantage, travel and rest taken out."),
    ("Attack and defence", "The rating's two halves: points a side scores above an average side, and points it keeps out."),
    ("Chance to win", "How often we think a side wins a match like this one. 70% still loses 3 times in 10."),
    ("Draw chance", "Rugby draws are rare (about 2 in 100 tests): we give the chance the final margin lands on zero."),
    ("Expected margin", "The points we expect the favourite to win by, on average. Half of tests land within about eight points of it."),
    ("Expected total", "The points we expect both sides to score together."),
    ("World Rugby rankings (our replica)", "World Rugby's points-exchange rankings, rebuilt by us from results with the "
     "published formula. From 28 September 2026 our table starts from the published points and adds every result since."),
    ("Points exchange", "What a result moves in the World Rugby rankings: the winner takes points from the loser, more for "
     "beating a stronger side, half as much again for winning by more than 15, double at a World Cup."),
    ("Bonus points", "A try bonus point for scoring four or more tries; a losing bonus point for losing by seven or fewer. "
     "The Six Nations adds three for a Grand Slam."),
    ("Grand Slam", "Winning all five Six Nations matches."),
    ("Triple Crown", "A Home Nation (England, Ireland, Scotland, Wales) beating the other three in one Six Nations."),
    ("Wooden spoon", "Finishing last in the Six Nations."),
    ("Per 80", "A rate per 80 minutes on the pitch (a full test). Minutes come from the substitutions."),
    ("Scrum value", "Our player value: points added per 80 minutes above a replacement-level player in the same "
     "position, from what each carry, break, tackle, turnover and penalty is worth to the scoreboard (a model fitted on "
     "past tests), plus goal kicking above an average kicker."),
    ("Replacement level", "The 20th percentile of the position among regular test players: the level a side can "
     "always find on the bench."),
    ("Percentile", "Where a player ranks among regular test players in the same position group: 90th means better than "
     "90 in 100."),
    ("Position groups", "Front row (props and hookers), locks, back row (flankers and number 8s), half-backs (scrum-halves "
     "and fly-halves), centres, back three (wings and full-backs)."),
    ("Opponent-adjusted", "A team stat shifted by how much its opponents usually allow: 400 metres against a side that "
     "concedes 500 is less than 400 against one that concedes 300."),
    ("Gain line", "The line across the pitch where a phase starts: a carry over it is going forwards."),
    ("Clean break", "A carry that goes through the defensive line."),
    ("Tackle success", "Tackles made out of tackles attempted (made plus missed)."),
    ("Tests in our data", "Appearances in the matches our source carries. Older and smaller tests are missing, so this "
     "is not a player's official cap count."),
    ("Calibration", "Whether our chances mean what they say: of the tests we gave 70%, about 70% should have gone that way."),
    ("Log loss and Brier score", "Scores for a forecast against what happened; lower is better. A coin flip on a "
     "two-way result scores 0.693 log loss and 0.25 Brier (rugby's rare draws make ours three-way)."),
    ("Tiers", "Tier one: the Six Nations and Rugby Championship sides. Tier two: the other regular World Cup sides "
     "(Fiji, Japan, Georgia, Samoa, Tonga, the Americas' and Iberia's leading sides and others). Tier three: everyone "
     "else. We use tiers for a new side's starting rating and to say where our forecasts have been tested."),
    ("Development and test years", "We choose every setting on 2004-2018 and score once on 2019 onwards, so the "
     "published accuracy is honest."),
    ("Provisional rating", "A side with fewer than five tests rated, or fewer than three tests against tier-one or tier-two "
     "opposition in four years. A rating is only pinned down against the sides a team actually plays, so these carry no "
     "rank; the World Rugby rank (our rebuild) is the better guide for them."),
    ("Rating uncertainty", "How sure we are of a side's rating. A new side starts very unsure and learns fast against "
     "established sides; a test between two unproven sides moves both much less (a Kalman filter)."),
    ("Game value", "A player's Scrum value in one test: what his own numbers were worth to the margin, minus what a "
     "replacement-level player of his position would have added in the same minutes."),
    ("Involvements", "Carries, tackles and rucks won added together, per 80 minutes: a forward's work rate."),
    ("Lineout throws won", "The share of a hooker's throws that his side wins; our source credits the lineout to the thrower."),
    ("Win chance through the test", "Our chance for the home side at each score, from the pre-match margin and spread: "
     "with less time left, the same lead is worth more."),
    ("Grades", "Each position group's best regulars by Scrum value, ranked against the ranked sides: A is the top 15%, "
     "F the bottom 15%."),
    ("Career caps", "A player's tests for his country over his whole career, from Wikipedia's squad and records tables; "
     "'tests in our data' counts only the tests our sources hold."),
    ("Result only (before 1891)", "The early home unions counted goals and tries with no common points system, so those "
     "tests carry the winner (W-L) but no score, and the scoring records start in 1891."),
    ("Referee tendencies", "Per referee: penalties and cards a test, the home side's share of the penalties, and how the "
     "home side did against our pre-match chances. Small samples swing; read the number of tests."),
    ("At altitude", "A home test at a venue 1,000 m or more above sea level (Johannesburg is 1,750 m, Pretoria 1,340 m) "
     "against visitors from lower down."),
    ("Weather at kick-off", "Temperature, wind and rain over the hours of the test, from Open-Meteo's reanalysis; known only "
     "afterwards, so it never enters our pre-match numbers. Upcoming tests show the forecast as issued."),
]


def build_index(data: Path, scopes: dict, now: datetime | None = None) -> dict:
    now = now or B.now_utc()
    idx = {"ok": True, "site": config.SITE, "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "scopes": scopes,
           "credit": "Results, line-ups, match statistics and bios from ESPN's public site data; historic results, referees "
                     "and caps from Wikipedia (CC BY-SA 4.0); weather data by Open-Meteo.com (CC BY 4.0).",
           "default": "men"}
    B.write(data / "index.json", idx)
    return idx


def build_search(data: Path, rows: list) -> int:
    seen, out = set(), []
    for r in rows:
        k = (r["t"], r["href"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    out.sort(key=lambda r: (-r.get("w", 0), r["t"]))
    return B.write(data / "search.json", out)


def build_glossary(data: Path) -> int:
    return B.write(data / "glossary.json", {"ok": True, "terms": [{"t": t, "d": d} for t, d in GLOSSARY]})
