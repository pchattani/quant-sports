# Data sources, credits and terms

The sites built from this repository (The Quant Footballer, Paddock, Hardwood, Ace, Bullpen, Gridiron and Rink)
are non-commercial. They publish model outputs and compact facts derived from the sources below, credit each
source on the site, and do not re-host raw feeds. The rule throughout: a source whose terms forbid reuse or
redistribution is not used (Nippon Professional Baseball's npb.jp, Basketball-Reference, Pro Football
Reference, Spotrac, HoopsHype and OverTheCap contracts are left out for that reason).

| Source | Used for | Terms / licence | What is in this repository |
|---|---|---|---|
| **Sofascore** (sofascore.com) | football fixtures, results, line-ups, player statistics, squads | Sofascore's terms; credited on the Footballer | **No raw Sofascore data.** The fetchers' code is here; the raw stores live in a private repository and are never published. The site shows derived facts and model output only. Club crests are not shipped. |
| **StatsBomb Open Data** | World Cup player and expected-goals aggregates (`oddsmarkets/sports/world_cup/data/`) | StatsBomb's open-data user agreement: free use with attribution | aggregates; credit: *Data provided by StatsBomb* |
| **Jolpica F1** (Ergast successor) | Formula 1 results, qualifying, laps and pit stops | free API; Formula 1 timing data belongs to Formula One Management | Paddock season stores (`docs/paddock/data/`) |
| **OpenF1** (openf1.org) | sessions, stints, race control, telemetry | unofficial, from F1 live timing; non-commercial | session records and telemetry **summaries**; raw telemetry is never committed |
| **ESPN** public JSON | NBA/WNBA play-by-play and box scores, tennis, MLB/NFL/NHL odds and scores | no published API terms; used non-commercially, credited | compact season stores and derived tables; raw responses are not published |
| **WTA** stats API | WTA draws, matches and match statistics | terms unstated | compact stores only |
| **tennis-data.co.uk** | tennis results and closing odds | free download | compact stores only |
| **Match Charting Project** (Jeff Sackmann and contributors) | tennis shot-level style profiles (`docs/ace/data/*/style.json`) and test excerpts | **CC BY-NC-SA 4.0** | the derived style tables, which are shared alike under CC BY-NC-SA 4.0 (licence and credit in each file's `_meta`) |
| **MLB Advanced Media** (MLB Stats API, Baseball Savant) | MLB and Triple-A games, pitch tables, live feeds | individual, non-commercial, non-bulk use; (c) MLB Advanced Media | compact game records only; raw feeds are never re-hosted; the test fixtures are synthetic |
| **Retrosheet** | historical MLB play-by-play and game logs | see notice below | test excerpts and derived history |
| **Chadwick Baseball Bureau** register | player identity crosswalk (`docs/bullpen/data/people.json`) | **ODC-BY 1.0** | the crosswalk; credit: *Chadwick Baseball Bureau* |
| **Lahman Baseball Database** (Sean Lahman) | history cross-checks | **CC BY-SA 3.0** | nothing raw |
| **nflverse** (nflverse-data releases) | NFL play-by-play, schedules, rosters, participation | **CC BY 4.0**; credit: *nflverse* | season stores, derived tables, test slices |
| **FTN Data** charting (via nflverse) | NFL charting fields | **CC BY-SA 4.0**; credit: *FTN Data via nflverse* | derived fields, shared alike |
| **NFL Next Gen Stats** (via nflverse) | NFL tracking aggregates | NFL data, informational use | derived fields only |
| **NHL** (api-web.nhle.com, api.nhle.com/stats) | NHL schedule, play-by-play, shifts, box scores, standings, EDGE | personal, non-commercial use; NHL and team marks are the NHL's | compact season stores and derived tables; raw responses are not published |
| **MoneyPuck** (moneypuck.com) | NHL expected-goals benchmark | free for non-commercial use with credit; credit: *MoneyPuck.com* | nothing raw |
| **Kalshi**, **Polymarket** | live prediction-market prices shown beside the models | the venues' API terms | prices are read at build time; no recorded market data is published |
| **football-data.co.uk** | historical football odds for calibration | free download | nothing raw (a local cache only) |

Retrosheet notice (verbatim, as its terms require):

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested
> parties may contact Retrosheet at "www.retrosheet.org".

Trademarks, team names and competition names belong to their owners. Nothing on the sites or in this repository
is affiliated with or endorsed by any league, team, governing body or data provider.

Because some sources are share-alike (CC BY-SA, CC BY-NC-SA), the derived data under `docs/ace/` and
`docs/gridiron/` cannot be offered under a more permissive licence than those sources allow; the repository's
`LICENSE` grants no rights over the code, and these terms govern the data.
