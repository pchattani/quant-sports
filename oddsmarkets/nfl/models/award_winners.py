"""
AP NFL award winners 2006-2025: the training labels for the award models.

VERIFIED 2026-10-01 (builder C) against the Wikipedia award-history pages, each fetched that day:
    https://en.wikipedia.org/wiki/AP_NFL_Most_Valuable_Player
    https://en.wikipedia.org/wiki/AP_NFL_Offensive_Player_of_the_Year
    https://en.wikipedia.org/wiki/AP_NFL_Defensive_Player_of_the_Year
    https://en.wikipedia.org/wiki/AP_NFL_Offensive_Rookie_of_the_Year
    https://en.wikipedia.org/wiki/AP_NFL_Defensive_Rookie_of_the_Year
    https://en.wikipedia.org/wiki/AP_NFL_Comeback_Player_of_the_Year
    https://en.wikipedia.org/wiki/AP_NFL_Coach_of_the_Year
2006-2024 also agree with the builder's own record; the 2025 season's winners (announced at NFL Honors, February
2026) were cross-checked on ESPN, "2026 NFL Honors: Who won the league's biggest awards?"
(https://www.espn.com/nfl/story/_/id/47810326/2026-nfl-honors-won-league-biggest-awards).

Seasons are the year the season started (2025 = the 2025 season, awarded February 2026). Each entry is
(name, nflverse team abbreviation of that season, position). No co-winners in 2006-2025 for these awards.
"""
from __future__ import annotations

HAND_ENTERED = False
SOURCES = [
    "https://en.wikipedia.org/wiki/AP_NFL_Most_Valuable_Player",
    "https://en.wikipedia.org/wiki/AP_NFL_Offensive_Player_of_the_Year",
    "https://en.wikipedia.org/wiki/AP_NFL_Defensive_Player_of_the_Year",
    "https://en.wikipedia.org/wiki/AP_NFL_Offensive_Rookie_of_the_Year",
    "https://en.wikipedia.org/wiki/AP_NFL_Defensive_Rookie_of_the_Year",
    "https://en.wikipedia.org/wiki/AP_NFL_Comeback_Player_of_the_Year",
    "https://en.wikipedia.org/wiki/AP_NFL_Coach_of_the_Year",
    "https://www.espn.com/nfl/story/_/id/47810326/2026-nfl-honors-won-league-biggest-awards",
]
VERIFIED = "2026-10-01"

WINNERS: dict[str, dict[int, tuple[str, str, str]]] = {
    "mvp": {
        2006: ("LaDainian Tomlinson", "SD", "RB"), 2007: ("Tom Brady", "NE", "QB"), 2008: ("Peyton Manning", "IND", "QB"),
        2009: ("Peyton Manning", "IND", "QB"), 2010: ("Tom Brady", "NE", "QB"), 2011: ("Aaron Rodgers", "GB", "QB"),
        2012: ("Adrian Peterson", "MIN", "RB"), 2013: ("Peyton Manning", "DEN", "QB"), 2014: ("Aaron Rodgers", "GB", "QB"),
        2015: ("Cam Newton", "CAR", "QB"), 2016: ("Matt Ryan", "ATL", "QB"), 2017: ("Tom Brady", "NE", "QB"),
        2018: ("Patrick Mahomes", "KC", "QB"), 2019: ("Lamar Jackson", "BAL", "QB"), 2020: ("Aaron Rodgers", "GB", "QB"),
        2021: ("Aaron Rodgers", "GB", "QB"), 2022: ("Patrick Mahomes", "KC", "QB"), 2023: ("Lamar Jackson", "BAL", "QB"),
        2024: ("Josh Allen", "BUF", "QB"), 2025: ("Matthew Stafford", "LA", "QB"),
    },
    "opoy": {
        2006: ("LaDainian Tomlinson", "SD", "RB"), 2007: ("Tom Brady", "NE", "QB"), 2008: ("Drew Brees", "NO", "QB"),
        2009: ("Chris Johnson", "TEN", "RB"), 2010: ("Tom Brady", "NE", "QB"), 2011: ("Drew Brees", "NO", "QB"),
        2012: ("Adrian Peterson", "MIN", "RB"), 2013: ("Peyton Manning", "DEN", "QB"), 2014: ("DeMarco Murray", "DAL", "RB"),
        2015: ("Cam Newton", "CAR", "QB"), 2016: ("Matt Ryan", "ATL", "QB"), 2017: ("Todd Gurley", "LA", "RB"),
        2018: ("Patrick Mahomes", "KC", "QB"), 2019: ("Michael Thomas", "NO", "WR"), 2020: ("Derrick Henry", "TEN", "RB"),
        2021: ("Cooper Kupp", "LA", "WR"), 2022: ("Justin Jefferson", "MIN", "WR"),
        2023: ("Christian McCaffrey", "SF", "RB"), 2024: ("Saquon Barkley", "PHI", "RB"),
        2025: ("Jaxon Smith-Njigba", "SEA", "WR"),
    },
    "dpoy": {
        2006: ("Jason Taylor", "MIA", "DE"), 2007: ("Bob Sanders", "IND", "S"), 2008: ("James Harrison", "PIT", "LB"),
        2009: ("Charles Woodson", "GB", "CB"), 2010: ("Troy Polamalu", "PIT", "S"), 2011: ("Terrell Suggs", "BAL", "LB"),
        2012: ("J. J. Watt", "HOU", "DE"), 2013: ("Luke Kuechly", "CAR", "LB"), 2014: ("J. J. Watt", "HOU", "DE"),
        2015: ("J. J. Watt", "HOU", "DE"), 2016: ("Khalil Mack", "OAK", "DE"), 2017: ("Aaron Donald", "LA", "DT"),
        2018: ("Aaron Donald", "LA", "DT"), 2019: ("Stephon Gilmore", "NE", "CB"), 2020: ("Aaron Donald", "LA", "DT"),
        2021: ("T. J. Watt", "PIT", "LB"), 2022: ("Nick Bosa", "SF", "DE"), 2023: ("Myles Garrett", "CLE", "DE"),
        2024: ("Patrick Surtain II", "DEN", "CB"), 2025: ("Myles Garrett", "CLE", "DE"),
    },
    "oroy": {
        2006: ("Vince Young", "TEN", "QB"), 2007: ("Adrian Peterson", "MIN", "RB"), 2008: ("Matt Ryan", "ATL", "QB"),
        2009: ("Percy Harvin", "MIN", "WR"), 2010: ("Sam Bradford", "STL", "QB"), 2011: ("Cam Newton", "CAR", "QB"),
        2012: ("Robert Griffin III", "WAS", "QB"), 2013: ("Eddie Lacy", "GB", "RB"),
        2014: ("Odell Beckham Jr.", "NYG", "WR"), 2015: ("Todd Gurley", "STL", "RB"), 2016: ("Dak Prescott", "DAL", "QB"),
        2017: ("Alvin Kamara", "NO", "RB"), 2018: ("Saquon Barkley", "NYG", "RB"), 2019: ("Kyler Murray", "ARI", "QB"),
        2020: ("Justin Herbert", "LAC", "QB"), 2021: ("Ja'Marr Chase", "CIN", "WR"), 2022: ("Garrett Wilson", "NYJ", "WR"),
        2023: ("C. J. Stroud", "HOU", "QB"), 2024: ("Jayden Daniels", "WAS", "QB"),
        2025: ("Tetairoa McMillan", "CAR", "WR"),
    },
    "droy": {
        2006: ("DeMeco Ryans", "HOU", "LB"), 2007: ("Patrick Willis", "SF", "LB"), 2008: ("Jerod Mayo", "NE", "LB"),
        2009: ("Brian Cushing", "HOU", "LB"), 2010: ("Ndamukong Suh", "DET", "DT"), 2011: ("Von Miller", "DEN", "LB"),
        2012: ("Luke Kuechly", "CAR", "LB"), 2013: ("Sheldon Richardson", "NYJ", "DE"), 2014: ("Aaron Donald", "STL", "DT"),
        2015: ("Marcus Peters", "KC", "CB"), 2016: ("Joey Bosa", "SD", "DE"), 2017: ("Marshon Lattimore", "NO", "CB"),
        2018: ("Shaquille Leonard", "IND", "LB"), 2019: ("Nick Bosa", "SF", "DE"), 2020: ("Chase Young", "WAS", "DE"),
        2021: ("Micah Parsons", "DAL", "LB"), 2022: ("Sauce Gardner", "NYJ", "CB"),
        2023: ("Will Anderson Jr.", "HOU", "DE"), 2024: ("Jared Verse", "LA", "LB"),
        2025: ("Carson Schwesinger", "CLE", "LB"),
    },
    "cpoy": {
        2006: ("Chad Pennington", "NYJ", "QB"), 2007: ("Greg Ellis", "DAL", "DE"), 2008: ("Chad Pennington", "MIA", "QB"),
        2009: ("Tom Brady", "NE", "QB"), 2010: ("Michael Vick", "PHI", "QB"), 2011: ("Matthew Stafford", "DET", "QB"),
        2012: ("Peyton Manning", "DEN", "QB"), 2013: ("Philip Rivers", "SD", "QB"), 2014: ("Rob Gronkowski", "NE", "TE"),
        2015: ("Eric Berry", "KC", "S"), 2016: ("Jordy Nelson", "GB", "WR"), 2017: ("Keenan Allen", "LAC", "WR"),
        2018: ("Andrew Luck", "IND", "QB"), 2019: ("Ryan Tannehill", "TEN", "QB"), 2020: ("Alex Smith", "WAS", "QB"),
        2021: ("Joe Burrow", "CIN", "QB"), 2022: ("Geno Smith", "SEA", "QB"), 2023: ("Joe Flacco", "CLE", "QB"),
        2024: ("Joe Burrow", "CIN", "QB"), 2025: ("Christian McCaffrey", "SF", "RB"),
    },
    "coty": {
        2006: ("Sean Payton", "NO", "HC"), 2007: ("Bill Belichick", "NE", "HC"), 2008: ("Mike Smith", "ATL", "HC"),
        2009: ("Marvin Lewis", "CIN", "HC"), 2010: ("Bill Belichick", "NE", "HC"), 2011: ("Jim Harbaugh", "SF", "HC"),
        2012: ("Bruce Arians", "IND", "HC"), 2013: ("Ron Rivera", "CAR", "HC"), 2014: ("Bruce Arians", "ARI", "HC"),
        2015: ("Ron Rivera", "CAR", "HC"), 2016: ("Jason Garrett", "DAL", "HC"), 2017: ("Sean McVay", "LA", "HC"),
        2018: ("Matt Nagy", "CHI", "HC"), 2019: ("John Harbaugh", "BAL", "HC"), 2020: ("Kevin Stefanski", "CLE", "HC"),
        2021: ("Mike Vrabel", "TEN", "HC"), 2022: ("Brian Daboll", "NYG", "HC"), 2023: ("Kevin Stefanski", "CLE", "HC"),
        2024: ("Kevin O'Connell", "MIN", "HC"), 2025: ("Mike Vrabel", "NE", "HC"),
    },
}
# Bruce Arians won in 2012 as Indianapolis's interim head coach (Chuck Pagano's leukaemia treatment); the schedules
# list Pagano as the Colts' coach for most games, so the COTY label is matched to the team, not the coach name.
INTERIM_TEAM_LABEL = {("coty", 2012): "IND"}
