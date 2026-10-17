"""
Past award winners: the training labels for the award-race models.

Originally hand-entered from memory (builder C, 2026-10-01); every entry VERIFIED 2026-10-01 against
the Wikipedia award-history pages (NBA Most Valuable Player / Rookie of the Year / Defensive Player of
the Year / Sixth Man of the Year / Most Improved Player / Clutch Player of the Year; WNBA Most Valuable
Player / Rookie of the Year / Defensive Player of the Year / Sixth Player of the Year / Most Improved
Player), with 2025-26 NBA and 2026 WNBA winners and the shared awards cross-checked on nba.com,
wnba.com, pr.nba.com and Yahoo Sports. Seasons are labelled by the year they end in (NBA
2024-25 = 2025; WNBA 2025 = 2025). None = not announced as of 2026-10-01 (WNBA 2026 MVP, DPOY and
Sixth Player). Ties (co-winners) are tuples.

Names are matched to ESPN player ids at run time by `oddsmarkets.basketball.models._io.fold_name`
(accent-, case- and suffix-insensitive), restricted to players who appeared in that season's store.
The Clutch Player of the Year (Jerry West Trophy) exists from 2023 (NBA only). WNBA Sixth Player
from 2007, Most Improved from 2000, Rookie from 1998.
"""
from __future__ import annotations

HAND_ENTERED = False

NBA: dict[str, dict[int, str | tuple | None]] = {
    "mvp": {
        1997: "Karl Malone", 1998: "Michael Jordan", 1999: "Karl Malone", 2000: "Shaquille O'Neal", 2001: "Allen Iverson",
        2002: "Tim Duncan", 2003: "Tim Duncan", 2004: "Kevin Garnett", 2005: "Steve Nash", 2006: "Steve Nash",
        2007: "Dirk Nowitzki", 2008: "Kobe Bryant", 2009: "LeBron James", 2010: "LeBron James", 2011: "Derrick Rose",
        2012: "LeBron James", 2013: "LeBron James", 2014: "Kevin Durant", 2015: "Stephen Curry", 2016: "Stephen Curry",
        2017: "Russell Westbrook", 2018: "James Harden", 2019: "Giannis Antetokounmpo", 2020: "Giannis Antetokounmpo",
        2021: "Nikola Jokic", 2022: "Nikola Jokic", 2023: "Joel Embiid", 2024: "Nikola Jokic",
        2025: "Shai Gilgeous-Alexander", 2026: "Shai Gilgeous-Alexander",
    },
    "roy": {
        1997: "Allen Iverson", 1998: "Tim Duncan", 1999: "Vince Carter", 2000: ("Elton Brand", "Steve Francis"),
        2001: "Mike Miller", 2002: "Pau Gasol", 2003: "Amar'e Stoudemire", 2004: "LeBron James", 2005: "Emeka Okafor",
        2006: "Chris Paul", 2007: "Brandon Roy", 2008: "Kevin Durant", 2009: "Derrick Rose", 2010: "Tyreke Evans",
        2011: "Blake Griffin", 2012: "Kyrie Irving", 2013: "Damian Lillard", 2014: "Michael Carter-Williams",
        2015: "Andrew Wiggins", 2016: "Karl-Anthony Towns", 2017: "Malcolm Brogdon", 2018: "Ben Simmons",
        2019: "Luka Doncic", 2020: "Ja Morant", 2021: "LaMelo Ball", 2022: "Scottie Barnes", 2023: "Paolo Banchero",
        2024: "Victor Wembanyama", 2025: "Stephon Castle", 2026: "Cooper Flagg",
    },
    "dpoy": {
        1997: "Dikembe Mutombo", 1998: "Dikembe Mutombo", 1999: "Alonzo Mourning", 2000: "Alonzo Mourning",
        2001: "Dikembe Mutombo", 2002: "Ben Wallace", 2003: "Ben Wallace", 2004: "Ron Artest", 2005: "Ben Wallace",
        2006: "Ben Wallace", 2007: "Marcus Camby", 2008: "Kevin Garnett", 2009: "Dwight Howard", 2010: "Dwight Howard",
        2011: "Dwight Howard", 2012: "Tyson Chandler", 2013: "Marc Gasol", 2014: "Joakim Noah", 2015: "Kawhi Leonard",
        2016: "Kawhi Leonard", 2017: "Draymond Green", 2018: "Rudy Gobert", 2019: "Rudy Gobert",
        2020: "Giannis Antetokounmpo", 2021: "Rudy Gobert", 2022: "Marcus Smart", 2023: "Jaren Jackson Jr.",
        2024: "Rudy Gobert", 2025: "Evan Mobley", 2026: "Victor Wembanyama",
    },
    "6moy": {
        1997: "John Starks", 1998: "Danny Manning", 1999: "Darrell Armstrong", 2000: "Rodney Rogers", 2001: "Aaron McKie",
        2002: "Corliss Williamson", 2003: "Bobby Jackson", 2004: "Antawn Jamison", 2005: "Ben Gordon", 2006: "Mike Miller",
        2007: "Leandro Barbosa", 2008: "Manu Ginobili", 2009: "Jason Terry", 2010: "Jamal Crawford", 2011: "Lamar Odom",
        2012: "James Harden", 2013: "J.R. Smith", 2014: "Jamal Crawford", 2015: "Lou Williams", 2016: "Jamal Crawford",
        2017: "Eric Gordon", 2018: "Lou Williams", 2019: "Lou Williams", 2020: "Montrezl Harrell", 2021: "Jordan Clarkson",
        2022: "Tyler Herro", 2023: "Malcolm Brogdon", 2024: "Naz Reid", 2025: "Payton Pritchard", 2026: "Keldon Johnson",
    },
    "mip": {
        1997: "Isaac Austin", 1998: "Alan Henderson", 1999: "Darrell Armstrong", 2000: "Jalen Rose", 2001: "Tracy McGrady",
        2002: "Jermaine O'Neal", 2003: "Gilbert Arenas", 2004: "Zach Randolph", 2005: "Bobby Simmons", 2006: "Boris Diaw",
        2007: "Monta Ellis", 2008: "Hedo Turkoglu", 2009: "Danny Granger", 2010: "Aaron Brooks", 2011: "Kevin Love",
        2012: "Ryan Anderson", 2013: "Paul George", 2014: "Goran Dragic", 2015: "Jimmy Butler", 2016: "CJ McCollum",
        2017: "Giannis Antetokounmpo", 2018: "Victor Oladipo", 2019: "Pascal Siakam", 2020: "Brandon Ingram",
        2021: "Julius Randle", 2022: "Ja Morant", 2023: "Lauri Markkanen", 2024: "Tyrese Maxey", 2025: "Dyson Daniels",
        2026: "Nickeil Alexander-Walker",
    },
    "clutch": {2023: "De'Aaron Fox", 2024: "Stephen Curry", 2025: "Jalen Brunson", 2026: "Shai Gilgeous-Alexander"},
}

WNBA: dict[str, dict[int, str | tuple | None]] = {
    "mvp": {
        1997: "Cynthia Cooper", 1998: "Cynthia Cooper", 1999: "Yolanda Griffith", 2000: "Sheryl Swoopes", 2001: "Lisa Leslie",
        2002: "Sheryl Swoopes", 2003: "Lauren Jackson", 2004: "Lisa Leslie", 2005: "Sheryl Swoopes", 2006: "Lisa Leslie",
        2007: "Lauren Jackson", 2008: "Candace Parker", 2009: "Diana Taurasi", 2010: "Lauren Jackson",
        2011: "Tamika Catchings", 2012: "Tina Charles", 2013: "Candace Parker", 2014: "Maya Moore",
        2015: "Elena Delle Donne", 2016: "Nneka Ogwumike", 2017: "Sylvia Fowles", 2018: "Breanna Stewart",
        2019: "Elena Delle Donne", 2020: "A'ja Wilson", 2021: "Jonquel Jones", 2022: "A'ja Wilson", 2023: "Breanna Stewart",
        2024: "A'ja Wilson", 2025: "A'ja Wilson", 2026: None,
    },
    "roy": {
        1998: "Tracy Reid", 1999: "Chamique Holdsclaw", 2000: "Betty Lennox", 2001: "Jackie Stiles", 2002: "Tamika Catchings",
        2003: "Cheryl Ford", 2004: "Diana Taurasi", 2005: "Temeka Johnson", 2006: "Seimone Augustus", 2007: "Armintie Price",
        2008: "Candace Parker", 2009: "Angel McCoughtry", 2010: "Tina Charles", 2011: "Maya Moore", 2012: "Nneka Ogwumike",
        2013: "Elena Delle Donne", 2014: "Chiney Ogwumike", 2015: "Jewell Loyd", 2016: "Breanna Stewart",
        2017: "Allisha Gray", 2018: "A'ja Wilson", 2019: "Napheesa Collier", 2020: "Crystal Dangerfield",
        2021: "Michaela Onyenwere", 2022: "Rhyne Howard", 2023: "Aliyah Boston", 2024: "Caitlin Clark",
        2025: "Paige Bueckers", 2026: "Olivia Miles",
    },
    "dpoy": {
        1997: "Teresa Weatherspoon", 1998: "Teresa Weatherspoon", 1999: "Yolanda Griffith", 2000: "Sheryl Swoopes",
        2001: "Debbie Black", 2002: "Sheryl Swoopes", 2003: "Sheryl Swoopes", 2004: "Lisa Leslie", 2005: "Tamika Catchings",
        2006: "Tamika Catchings", 2007: "Lauren Jackson", 2008: "Lisa Leslie", 2009: "Tamika Catchings",
        2010: "Tamika Catchings", 2011: "Sylvia Fowles", 2012: "Tamika Catchings", 2013: "Sylvia Fowles",
        2014: "Brittney Griner", 2015: "Brittney Griner", 2016: "Sylvia Fowles", 2017: "Alana Beard", 2018: "Alana Beard",
        2019: "Natasha Howard", 2020: "Candace Parker", 2021: "Sylvia Fowles", 2022: "A'ja Wilson", 2023: "A'ja Wilson",
        2024: "Napheesa Collier", 2025: ("Alanna Smith", "A'ja Wilson"), 2026: None,
    },
    "6moy": {
        2007: "Plenette Pierson", 2008: "Candice Wiggins", 2009: "DeWanna Bonner", 2010: "DeWanna Bonner",
        2011: "DeWanna Bonner", 2012: "Renee Montgomery", 2013: "Riquna Williams", 2014: "Allie Quigley",
        2015: "Allie Quigley", 2016: "Jantel Lavender", 2017: "Sugar Rodgers", 2018: "Jonquel Jones", 2019: "Dearica Hamby",
        2020: "Dearica Hamby", 2021: "Kelsey Plum", 2022: "Brionna Jones", 2023: "Alysha Clark", 2024: "Tiffany Hayes",
        2025: "Naz Hillmon", 2026: None,
    },
    "mip": {
        2000: "Tari Phillips", 2001: "Janeth Arcain", 2002: "Coco Miller", 2003: "Michelle Snow", 2004: ("Kelly Miller", "Wendy Palmer"),
        2005: "Nicole Powell", 2006: "Erin Buescher", 2007: "Janel McCarville", 2008: "Ebony Hoffman",
        2009: "Crystal Langhorne", 2010: "Leilani Mitchell", 2011: "Kia Vaughn", 2012: "Kristi Toliver",
        2013: "Shavonte Zellous", 2014: "Skylar Diggins", 2015: "Kelsey Bone", 2016: "Elizabeth Williams",
        2017: "Jonquel Jones", 2018: "Natasha Howard", 2019: "Leilani Mitchell", 2020: "Betnijah Laney",
        2021: "Brionna Jones", 2022: "Jackie Young", 2023: "Satou Sabally", 2024: "DiJonai Carrington",
        2025: "Veronica Burton", 2026: "Jessica Shepard",
    },
}

# entries not yet verified against a published source (all verified 2026-10-01)
UNSURE = {"nba": [], "wnba": []}

AWARDS = ["mvp", "roy", "dpoy", "6moy", "mip", "clutch"]


def winners(league: str, award: str) -> dict[int, str | tuple | None]:
    return dict((NBA if str(league).lower() == "nba" else WNBA).get(award, {}))


def winner_names(league: str, award: str, season: int) -> list[str]:
    w = winners(league, award).get(int(season))
    if w is None:
        return []
    return list(w) if isinstance(w, tuple) else [w]
