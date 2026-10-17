"""
NHL award winners 2009-10 to 2025-26: the training labels for the award models.

VERIFIED 2026-10-01 (builder C) against the Wikipedia trophy pages' winners tables, each fetched that day:
    https://en.wikipedia.org/wiki/Hart_Memorial_Trophy
    https://en.wikipedia.org/wiki/Vezina_Trophy
    https://en.wikipedia.org/wiki/James_Norris_Memorial_Trophy
    https://en.wikipedia.org/wiki/Calder_Memorial_Trophy
    https://en.wikipedia.org/wiki/Art_Ross_Trophy
    https://en.wikipedia.org/wiki/Maurice_%22Rocket%22_Richard_Trophy
    https://en.wikipedia.org/wiki/Frank_J._Selke_Trophy
2009-10 to 2024-25 also agree with the builder's own record; 2025-26 (awarded June 2026) is taken from those pages.

Keys are NHL season ids (20252026 = the 2025-26 season). Each entry is (name, team tri-code of that season) or, for
the Art Ross and Rocket Richard trophies, (name, team, points / goals). The Rocket Richard Trophy was shared in
2009-10 (Crosby, Stamkos, 51) and 2019-20 (Ovechkin, Pastrnak, 48): those seasons list both.
"""
from __future__ import annotations

HAND_ENTERED = False
VERIFIED = "2026-10-01"
SOURCES = [
    "https://en.wikipedia.org/wiki/Hart_Memorial_Trophy",
    "https://en.wikipedia.org/wiki/Vezina_Trophy",
    "https://en.wikipedia.org/wiki/James_Norris_Memorial_Trophy",
    "https://en.wikipedia.org/wiki/Calder_Memorial_Trophy",
    "https://en.wikipedia.org/wiki/Art_Ross_Trophy",
    "https://en.wikipedia.org/wiki/Maurice_%22Rocket%22_Richard_Trophy",
    "https://en.wikipedia.org/wiki/Frank_J._Selke_Trophy",
]


def _s(y: int) -> int:
    return y * 10000 + y + 1


WINNERS: dict[str, dict[int, list[tuple]]] = {
    "hart": {
        _s(2009): [("Henrik Sedin", "VAN")], _s(2010): [("Corey Perry", "ANA")], _s(2011): [("Evgeni Malkin", "PIT")],
        _s(2012): [("Alex Ovechkin", "WSH")], _s(2013): [("Sidney Crosby", "PIT")], _s(2014): [("Carey Price", "MTL")],
        _s(2015): [("Patrick Kane", "CHI")], _s(2016): [("Connor McDavid", "EDM")], _s(2017): [("Taylor Hall", "NJD")],
        _s(2018): [("Nikita Kucherov", "TBL")], _s(2019): [("Leon Draisaitl", "EDM")], _s(2020): [("Connor McDavid", "EDM")],
        _s(2021): [("Auston Matthews", "TOR")], _s(2022): [("Connor McDavid", "EDM")], _s(2023): [("Nathan MacKinnon", "COL")],
        _s(2024): [("Connor Hellebuyck", "WPG")], _s(2025): [("Nikita Kucherov", "TBL")],
    },
    "vezina": {
        _s(2009): [("Ryan Miller", "BUF")], _s(2010): [("Tim Thomas", "BOS")], _s(2011): [("Henrik Lundqvist", "NYR")],
        _s(2012): [("Sergei Bobrovsky", "CBJ")], _s(2013): [("Tuukka Rask", "BOS")], _s(2014): [("Carey Price", "MTL")],
        _s(2015): [("Braden Holtby", "WSH")], _s(2016): [("Sergei Bobrovsky", "CBJ")], _s(2017): [("Pekka Rinne", "NSH")],
        _s(2018): [("Andrei Vasilevskiy", "TBL")], _s(2019): [("Connor Hellebuyck", "WPG")],
        _s(2020): [("Marc-Andre Fleury", "VGK")], _s(2021): [("Igor Shesterkin", "NYR")], _s(2022): [("Linus Ullmark", "BOS")],
        _s(2023): [("Connor Hellebuyck", "WPG")], _s(2024): [("Connor Hellebuyck", "WPG")],
        _s(2025): [("Andrei Vasilevskiy", "TBL")],
    },
    "norris": {
        _s(2009): [("Duncan Keith", "CHI")], _s(2010): [("Nicklas Lidstrom", "DET")], _s(2011): [("Erik Karlsson", "OTT")],
        _s(2012): [("P. K. Subban", "MTL")], _s(2013): [("Duncan Keith", "CHI")], _s(2014): [("Erik Karlsson", "OTT")],
        _s(2015): [("Drew Doughty", "LAK")], _s(2016): [("Brent Burns", "SJS")], _s(2017): [("Victor Hedman", "TBL")],
        _s(2018): [("Mark Giordano", "CGY")], _s(2019): [("Roman Josi", "NSH")], _s(2020): [("Adam Fox", "NYR")],
        _s(2021): [("Cale Makar", "COL")], _s(2022): [("Erik Karlsson", "SJS")], _s(2023): [("Quinn Hughes", "VAN")],
        _s(2024): [("Cale Makar", "COL")], _s(2025): [("Zach Werenski", "CBJ")],
    },
    "calder": {
        _s(2009): [("Tyler Myers", "BUF")], _s(2010): [("Jeff Skinner", "CAR")], _s(2011): [("Gabriel Landeskog", "COL")],
        _s(2012): [("Jonathan Huberdeau", "FLA")], _s(2013): [("Nathan MacKinnon", "COL")], _s(2014): [("Aaron Ekblad", "FLA")],
        _s(2015): [("Artemi Panarin", "CHI")], _s(2016): [("Auston Matthews", "TOR")], _s(2017): [("Mathew Barzal", "NYI")],
        _s(2018): [("Elias Pettersson", "VAN")], _s(2019): [("Cale Makar", "COL")], _s(2020): [("Kirill Kaprizov", "MIN")],
        _s(2021): [("Moritz Seider", "DET")], _s(2022): [("Matty Beniers", "SEA")], _s(2023): [("Connor Bedard", "CHI")],
        _s(2024): [("Lane Hutson", "MTL")], _s(2025): [("Matthew Schaefer", "NYI")],
    },
    "ross": {
        _s(2009): [("Henrik Sedin", "VAN", 112)], _s(2010): [("Daniel Sedin", "VAN", 104)],
        _s(2011): [("Evgeni Malkin", "PIT", 109)], _s(2012): [("Martin St. Louis", "TBL", 60)],
        _s(2013): [("Sidney Crosby", "PIT", 104)], _s(2014): [("Jamie Benn", "DAL", 87)], _s(2015): [("Patrick Kane", "CHI", 106)],
        _s(2016): [("Connor McDavid", "EDM", 100)], _s(2017): [("Connor McDavid", "EDM", 108)],
        _s(2018): [("Nikita Kucherov", "TBL", 128)], _s(2019): [("Leon Draisaitl", "EDM", 110)],
        _s(2020): [("Connor McDavid", "EDM", 105)], _s(2021): [("Connor McDavid", "EDM", 123)],
        _s(2022): [("Connor McDavid", "EDM", 153)], _s(2023): [("Nikita Kucherov", "TBL", 144)],
        _s(2024): [("Nikita Kucherov", "TBL", 121)], _s(2025): [("Connor McDavid", "EDM", 138)],
    },
    "richard": {
        _s(2009): [("Sidney Crosby", "PIT", 51), ("Steven Stamkos", "TBL", 51)], _s(2010): [("Corey Perry", "ANA", 50)],
        _s(2011): [("Steven Stamkos", "TBL", 60)], _s(2012): [("Alex Ovechkin", "WSH", 32)],
        _s(2013): [("Alex Ovechkin", "WSH", 51)], _s(2014): [("Alex Ovechkin", "WSH", 53)],
        _s(2015): [("Alex Ovechkin", "WSH", 50)], _s(2016): [("Sidney Crosby", "PIT", 44)],
        _s(2017): [("Alex Ovechkin", "WSH", 49)], _s(2018): [("Alex Ovechkin", "WSH", 51)],
        _s(2019): [("Alex Ovechkin", "WSH", 48), ("David Pastrnak", "BOS", 48)], _s(2020): [("Auston Matthews", "TOR", 41)],
        _s(2021): [("Auston Matthews", "TOR", 60)], _s(2022): [("Connor McDavid", "EDM", 64)],
        _s(2023): [("Auston Matthews", "TOR", 69)], _s(2024): [("Leon Draisaitl", "EDM", 52)],
        _s(2025): [("Nathan MacKinnon", "COL", 53)],
    },
    "selke": {
        _s(2009): [("Pavel Datsyuk", "DET")], _s(2010): [("Ryan Kesler", "VAN")], _s(2011): [("Patrice Bergeron", "BOS")],
        _s(2012): [("Jonathan Toews", "CHI")], _s(2013): [("Patrice Bergeron", "BOS")], _s(2014): [("Patrice Bergeron", "BOS")],
        _s(2015): [("Anze Kopitar", "LAK")], _s(2016): [("Patrice Bergeron", "BOS")], _s(2017): [("Anze Kopitar", "LAK")],
        _s(2018): [("Ryan O'Reilly", "STL")], _s(2019): [("Sean Couturier", "PHI")], _s(2020): [("Aleksander Barkov", "FLA")],
        _s(2021): [("Patrice Bergeron", "BOS")], _s(2022): [("Patrice Bergeron", "BOS")], _s(2023): [("Aleksander Barkov", "FLA")],
        _s(2024): [("Aleksander Barkov", "FLA")], _s(2025): [("Nick Suzuki", "MTL")],
    },
}
# name spellings in NHL feeds that differ from the trophy pages
ALIASES = {"Alex Ovechkin": ["Alexander Ovechkin"], "P. K. Subban": ["P.K. Subban", "PK Subban"],
           "Marc-Andre Fleury": ["Marc-André Fleury"], "Anze Kopitar": ["Anže Kopitar"], "Nicklas Lidstrom": ["Nicklas Lidström"],
           "Tim Thomas": ["Timothy Thomas"], "Mitch Marner": ["Mitchell Marner"]}
