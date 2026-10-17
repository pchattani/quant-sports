"""
Plain single-table leagues, and leagues with conferences and a playoff.

One package serves every competition whose season is a round-robin table with
qualification and relegation decided by finishing position: the Premier League,
La Liga, Serie A, the Bundesliga, Ligue 1, the Eredivisie, the Primeira Liga, the
Brasileirão, the Saudi Pro League — and MLS, whose two conferences and re-seeded
playoff are the one structural addition.

The Argentine Liga Profesional keeps its own package (`competitions/liga`): its
zones, Tabla Anual, promedios and champion-dependent continental berths are a
different shape, and forcing them through this one would make both worse.
"""
