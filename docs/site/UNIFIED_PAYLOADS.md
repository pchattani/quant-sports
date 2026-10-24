# Unified payloads: people, clubs, seasons

Contract between the build (`scripts/build_site_all.py` `build_unified()`, which drives
`oddsmarkets/football/analytics/unified.py`) and the front end (`docs/site/index.html`,
`docs/site/assets/**`). Written 2 October 2026 for the redesign. Everything listed
under "Existing" keeps working unchanged; everything under "New" is additive.

All paths are relative to `docs/site/data/`. All JSON is UTF-8, compact. Ids are
**strings** in JSON keys and **numbers or strings** in values exactly as noted.
Absent keys mean "unknown"; nulls are avoided.

---

## 0. Vocabulary

| Term | Meaning |
|---|---|
| `pid` | Sofascore player id (string). One person = one pid, everywhere. |
| `tid` | Sofascore team id (string in keys, int in values). One club or national team = one tid, everywhere. |
| `slug` | Competition slug (`premier-league`, `fa-cup`, `world-cup`, `liga-argentina`, ...). |
| `sid` | Sofascore season id of one edition of one competition (int). Unique per competition-season; **the season key in every URL and directory**. Exception: `liga-argentina`, whose store holds a calendar year split into two torneos, uses strings `"2026-clausura"`, `"2026-apertura"`. |
| `season` | The edition's display label as Sofascore names it, shortened: `"26/27"`, `"2026"`, `"Apertura 2026"`, `"Clausura 2026"`. |
| `era` | A cross-competition grouping key for "single season" filters on person and club pages: `"2026/27"` for a split-year season, `"2026"` for a calendar-year one. Derived from `season`: `"26/27"` -> `"2026/27"`; `"2026"` -> `"2026"`; Liga MX / Argentina halves -> their calendar year. |
| `kind` | Competition kind, one of `league`, `domestic_cup`, `super_cup`, `continental_club`, `international`. |
| `scope` | `club` (every kind except `international`) or `international`. Present on every row so "Club only / International only" is a one-key filter. |

Kind of each competition: the 12 leagues and `liga-argentina` are `league`; cup
family `domestic` -> `domestic_cup`; `super` -> `super_cup`; `cup` (UCL, UEL, UECL,
Libertadores, Sudamericana, AFC/CAF/CONCACAF club cups, Leagues Cup, Club World Cup,
Intercontinental Cup) -> `continental_club`; `international` -> `international`.
`competitions.json` carries `kind_u` (this value) and `scope` on every entry.

---

## 1. Season dimension

### 1.1 `competitions.json` (existing file, new keys per entry)

```jsonc
{
  "slug": "premier-league", ...existing keys...,
  "kind_u": "league", "scope": "club",
  "current_season": {"sid": 96668, "season": "26/27", "era": "2026/27",
                     "status": "current" | "last_edition"},
  "seasons": [ {"sid": 96668, "season": "26/27", "era": "2026/27", "source": "live"},
               {"sid": 76986, "season": "25/26", "era": "2025/26", "source": "store"},
               {"sid": 61627, "season": "24/25", "era": "2024/25", "source": "archive"}, ... ]
}
```

- Newest first. `source`:
  - `live` - the current edition; its payloads are the existing ones in `data/<slug>/`.
  - `store` - a past edition whose matches are in the competition's store: full
    results, a table computed from them (or the official one from the archive when
    present), and player/club lines where match detail exists.
  - `archive` - an older edition known only from the archive: official standings
    and the season's top players by category. No match list.
- `status: "last_edition"` means the competition has no edition in progress or
  scheduled (Euro 2024 until the 2028 cycle, Copa América 2024, Gold Cup 2025, AFCON
  2025, ...). The UI should label it "Last edition: <season>" and not "current".
  Odds, simulations and market tabs are absent for such a competition (they are
  already absent for internationals).

### 1.2 `data/<slug>/seasons.json` (new)

Same list as above with more detail, for the season picker of one competition:

```jsonc
{
  "slug": "premier-league", "current": 96668,
  "seasons": [
    {"sid": 96668, "season": "26/27", "era": "2026/27", "name": "Premier League 26/27",
     "source": "live", "path": "",                      // "" = the existing payloads in data/<slug>/
     "matches": 380, "finished": 50, "detail": 50},
    {"sid": 76986, "season": "25/26", "era": "2025/26", "name": "Premier League 25/26",
     "source": "store", "path": "s/76986/",
     "matches": 380, "finished": 380, "detail": 6,
     "champion": {"team": "Arsenal", "tid": 42}},        // when known
    {"sid": 61627, "season": "24/25", "era": "2024/25", "name": "Premier League 24/25",
     "source": "archive", "path": "s/61627/", "champion": {...}}
  ],
  "updated_at": "..."
}
```

### 1.3 `data/<slug>/s/<sid>/season.json` (new; one file per past season)

```jsonc
{
  "slug": "premier-league", "sid": 76986, "season": "25/26", "era": "2025/26",
  "name": "Premier League 25/26", "source": "store" | "archive",
  "standings": [                // same row shape as table.json "standings" rows, minus model columns
     {"pos": 1, "team": "Arsenal", "tid": 42, "played": 38, "w": 26, "d": 8, "l": 4,
      "gf": 80, "ga": 30, "gd": 50, "pts": 86, "group": null, "note": "Champions League"}
  ],
  "standings_source": "official" | "computed",   // archive table, or computed from results
  "groups": ["A", "B", ...],                       // cups with groups; standings rows carry "group"
  "fixtures": [                 // store seasons only; same row shape as fixtures.json "matches" (no "model")
     {"id": "12345", "date": "...", "round": 1, "stage": "league", "status": "finished",
      "home": "Arsenal", "away": "Chelsea", "home_id": 42, "away_id": 38, "hs": 2, "as": 1,
      "xg": [1.8, 0.9], "detail": true, "agg_winner": null, "winner": null}
  ],
  "bracket": [ {"round": "final", "home": ..., "away": ..., "hs": ..., "as": ..., "winner": ...} ],  // knockout ties, when any
  "players": [ ...players_live.json rows (same keys, percentiles within this season)... ],   // store seasons with detail only
  "metrics": [...],             // present when "players" is
  "leaders": {"goals": [{"id": "839956", "name": "...", "team": "...", "tid": 17, "value": 27}], "assists": [...], "rating": [...], ...},
  "detail_matches": 6,          // how many matches the player lines come from: say so in the UI when small
  "updated_at": "..."
}
```

- Archive seasons have `standings` (official) and `leaders` (Sofascore's top players
  of that season, by category) only.
- Match pages for past-season matches with detail are written to the existing
  `data/<slug>/matches/<id>.json` shard, so `#/match/...` links keep working.
- `history/<slug>.json` (existing, built from the archive) is kept for the old UI
  and is superseded by `seasons.json` + `s/<sid>/season.json`.

---

## 2. People registry

### 2.1 `data/people_index.json` (new; one row per person, deduplicated)

Column-oriented for size:

```jsonc
{
  "fields": ["id", "name", "pos", "nat", "dob", "club_tid", "club", "nt_tid", "nt",
             "comps", "min", "last"],
  "rows": [
    ["839956", "Erling Haaland", "F", "NOR", "2000-07-21", 17, "Manchester City", 4705, "Norway",
     ["premier-league", "champions-league", "wc-qual-uefa"], 1234, "2026-09-27"]
  ],
  "updated_at": "..."
}
```

- `club_tid`/`club` - the **current club** (section 2.3). `nt_tid`/`nt` - the national
  team he last played for (absent if none).
- `comps` - slugs he has appearances in, current era first. `min` - minutes in the
  current era across all competitions. `last` - date of his latest appearance.
- Sorted by `min` descending. Search should use this file instead of `search.json`'s
  player list (which has one row per player per competition).

### 2.2 `data/people/<pid>.json` (new; one file per person)

```jsonc
{
  "id": "82474", "name": "Ander Herrera", "short_name": "A. Herrera", "slug": "ander-herrera",
  "pos": "M", "nat": "ESP", "dob": "1989-08-14", "age": 37, "height": 182, "shirt": "21",
  "current_club": {"tid": 3202, "name": "Boca Juniors", "source": "roster" | "appearances" | "profile",
                   "as_of": "2026-10-02"},      // absent when unknown (e.g. retired / free agent)
  "national_team": {"tid": 4698, "name": "Spain"},
  "comps": {                                   // lookup for the rows below
     "liga-argentina": {"name": "Liga Argentina", "kind": "league", "scope": "club"},
     "libertadores":   {"name": "Libertadores", "kind": "continental_club", "scope": "club"}
  },
  "teams": {"3202": {"name": "Boca Juniors", "national": false, "crest": "assets/crests/3202.png"}},
  "apps_fields": ["date", "gid", "comp", "sid", "tid", "opp_tid", "opp", "home", "res", "start",
                  "min", "g", "a", "xg", "xa", "rt", "sh", "kp", "yc", "rc"],
  "apps": [                                     // every appearance in every store, newest first
     ["2026-05-29", "13981234", "libertadores", 87760, 3202, 4567, "Universidad Catolica", 1, "W 2-0", 0,
      45, 0, 0, 0.02, 0.10, 6.8, 0, 1, 0, 0]
  ],
  "seasons": [                                  // one row per (competition, season, team)
     {"comp": "liga-argentina", "kind": "league", "scope": "club", "sid": 87913, "season": "Apertura 2026",
      "era": "2026", "tid": 3202, "team": "Boca Juniors", "source": "store",
      "apps": 12, "starts": 9, "min": 550, "g": 1, "a": 2, "xg": 0.9, "xa": 1.1, "rt": 6.9,
      "line": { ...the full players_live.json row for that competition-season when it exists... }}
  ],
  "archive": [                                  // careers from the archive (older seasons, Sofascore's season totals)
     {"comp": "la-liga", "tournament": "LaLiga", "kind": "league", "scope": "club", "season": "18/19",
      "era": "2018/19", "team": "Athletic Club", "apps": 30, "min": 2300, "g": 3, "a": 4, "rt": 7.0, "source": "archive"}
  ],
  "transfers": [ {"date": "2026-07-01", "from_tid": 3202, "from": "Boca Juniors", "to_tid": ..., "to": "...", "type": "free"} ],  // when fetched
  "updated_at": "..."
}
```

Filtering in the UI: All = every row; Club only = `scope == "club"`; International
only = `scope == "international"`; one competition = `comp == slug`; one season =
`era == X`. `seasons` is the pre-aggregated table; `apps` is the match log for
charts and for any custom aggregate (e.g. a calendar window). `archive` rows are
season totals only (no match log) and never overlap a `seasons` row for the same
competition-season (the store wins).

### 2.3 What "current club" means

In order of preference:

1. `roster` - the club whose current Sofascore squad (`/team/{tid}/players`, fetched
   on a rotation into `data/squads/store.json`) lists him. If two rosters list him (a
   loan, or a stale roster), the more recently fetched wins.
2. `profile` - `player_details` (`/player/{pid}`, in the archive) names a club and
   that profile is newer than his last appearance.
3. `appearances` - the club of his latest club appearance across **all** stores.
   Only used when no roster covers any of his candidate clubs.

A player listed by no fetched roster whose latest-appearance club **has** a fetched
roster is treated as having left: no `current_club` (or the `profile` club), and he
is not in that club's squad.

---

## 3. Club registry

### 3.1 `data/clubs_index.json` (new; one row per club or national team)

```jsonc
{
  "fields": ["id", "name", "slug", "country", "national", "crest", "home", "comps", "colour", "alt"],
  "rows": [[17, "Manchester City", "manchester-city", "ENG", 0, "assets/crests/17.png",
            "premier-league", ["premier-league", "champions-league", "efl-cup", "fa-cup"], "#143a6c", "#eecb7a"]],
  "updated_at": "..."
}
```

`home` - the club's domestic league slug (or `null` if it plays in no followed
league); `national` - 1 for a national team. Replaces `search.json`'s team list
(which has PSG seven times). `colour` / `alt` - the club's main and second kit colours ("#rrggbb", or `null`) for
the Broadcast heroes, stripes and bars (`docs/_design/MIGRATION_V4.md`), from the committed table
`oddsmarkets/football/analytics/data/club_colours.json` (`[colour, alt, source]` per club id;
`oddsmarkets/football/analytics/colours.py`), so CI writes them without the crests. Precedence: Sofascore's
`teamColors` (kept by the fetchers from the answers they already receive, in `data/sofascore_colours.json`), then a
hand-checked override for top clubs whose crest misleads, then the colours derived from the club's crest on the PC
(`data/crest_colours.json`). A row without colours (national teams, clubs in none of the three: the kit falls back
to cobalt v slate) stops at `comps`; `alt` may be `null`. The club file (3.2) carries the same two keys when known.

### 3.2 `data/clubs/<tid>.json` (new; one file per club or national team)

```jsonc
{
  "id": 17, "name": "Manchester City", "slug": "manchester-city", "country": "ENG",
  "national": false, "crest": "assets/crests/17.png", "home": "premier-league",
  "names": {"premier-league": "Manchester City", "champions-league": "Man City"},   // name per competition, for routing into existing pages
  "squad": {
    "source": "roster" | "appearances", "as_of": "2026-09-30",
    "players": [ {"id": "839956", "name": "Erling Haaland", "pos": "F", "shirt": "9",
                  "nat": "NOR", "dob": "2000-07-21", "age": 26, "height": 195,
                  "min": 450, "apps": 5, "g": 5, "a": 0, "rt": 7.6} ]           // current-era club minutes and totals
  },
  "seasons": [   // one row per (competition, season)
    {"comp": "premier-league", "kind": "league", "scope": "club", "sid": 96668, "season": "26/27",
     "era": "2026/27", "source": "live",
     "pos": 1, "played": 6, "w": 5, "d": 1, "l": 0, "gf": 15, "ga": 4, "pts": 16,     // league / group position when any
     "stage": "league" | "r16" | "final" | "winner" | ...,                         // how far it went in a cup
     "rating": {"attack": 1.62, "defence": 0.71, "elo": 1712}                     // the model's strength, current seasons
    }
  ],
  "matches": [   // every match in every store, newest first (all seasons in the stores)
    {"id": "12345", "comp": "premier-league", "sid": 96668, "date": "...", "home": 1, "opp_tid": 38,
     "opp": "Chelsea", "status": "finished", "gf": 2, "ga": 1, "xg": [1.8, 0.9], "detail": true,
     "model": {"h": 0.55, "d": 0.24, "a": 0.21}}
  ],
  "pool": {"rating": 1.23, "rank": 3},          // pooled cross-league strength (clubs only), when fitted
  "updated_at": "..."
}
```

- National teams (`national: true`) have the same shape: `squad.source` is
  `appearances` (the latest call-up: players who appeared in its last
  international window), `seasons` are their tournament/qualifier editions.

---

## 4. Squads store (fetcher output; never loaded by the page)

`data/squads/store.json`, written by `scripts/fetch_sofascore_squads.py`, committed by
the hourly task with the other stores:

```jsonc
{"teams": {"3202": {"name": "Boca Juniors", "fetched_at": "2026-10-02T05:01:00Z",
                    "players": [{"id": "...", "n": "...", "pos": "M", "no": "21",
                                 "dob": 619056000, "c": "ARG", "h": 182}]}},
 "meta": {"updated_at": "..."}}
```

---

## 5. Removed

- `data/ballon-dor/` and the `#/ballon-dor` page's data. The build no longer writes
  it. The front end should drop the nav entry and the route (`core.js` nav,
  `global.js` page) and any Ballon d'Or text in the methodology/glossary.
- `glossary.json` loses its Ballon d'Or entries.

---

## 6. Backwards compatibility

Unchanged: `competitions.json` (new keys only), `hub.json`, `search.json`,
`season_index.json`, `pool.json` (`players_global.json` and `players_lab*.json`: retired, section 14),
`nations.json`, `careers/`, `history/`, and every `data/<slug>/*.json` current-season
payload. They can be retired by the front end once it reads the new files; tell the
backend and they will be dropped from the build.

---

## 7. Front-end changes requested (for the front-end agent)

1. Season picker on every competition page, from `competitions.json` `seasons`
   (or `data/<slug>/seasons.json`); a past season renders from
   `data/<slug>/s/<sid>/season.json` (table, results, bracket, players, leaders) and
   hides model tabs (probs, power, market, history).
2. `status: "last_edition"` competitions: label "Last edition" instead of current.
3. Person page `#/player/<pid>` from `data/people/<pid>.json`, with an
   All / Club / International / competition / season filter over `seasons` and `apps`,
   showing `current_club`.
4. Club page by team id (e.g. `#/club/<tid>`) from `data/clubs/<tid>.json`, with the
   same filters over `seasons` and `matches`; the squad from `squad.players`. Existing
   `#/<slug>/team/<club>` links can redirect via `names`.
5. Search from `people_index.json` and `clubs_index.json` (one row per entity).
6. Remove the Ballon d'Or nav entry, route and copy.
7. Club squad lists in competition pages (`pages.js` around line 317, which filters
   `players_live` by latest club in that store) should read `clubs/<tid>.json`
   `squad.players` instead, so a player who left is not listed.

---

## 8. Front-end requests

From the front-end agent, 2 October 2026. The front end (core.js, seasons.js, people.js)
is built against sections 1-3 as written; these are the points it relies on or would
like settled. Nothing here blocks: each has a fallback in the page.

1. **Standings rows carry `tid`, archive seasons included.** Archive tables spell clubs
   differently from the stores ("Liverpool FC", "Brighton & Hove Albion"); without a
   `tid` the page folds names to find the club, and some still miss. Same for
   `leaders` rows (`tid` beside `team`) and `bracket` ties (`home_id`, `away_id`).
2. **`champion` only when the winner is known.** For a cup, an archive season's
   standings are its league or group phase; the top row is not the winner. Please set
   `seasons.json` `champion` for cups only from a final (or leave it out). The page
   labels a cup's top row "Top of the league phase", never "Champion".
3. **`clubs/<tid>.json` `matches[].model`**: the page reads `h/d/a` as the fixture's
   home / draw / away (as in `fixtures.json`), not from the club's side. Please keep it
   that way, or say so if it is the club's perspective.
4. **`people/<pid>.json` `apps[].res`** is read as "W 2-0" from the player's side
   (first letter W/D/L, then goals for-against). `apps[].tid` should match a key of
   `teams` so the "For" column can name the team.
5. **Every `ok` competition has `current_season.sid`** (the season picker's value for
   the live edition, and `?s=` routing compares against it). Liga Argentina and the
   Liga MX halves need it too.
6. **Keep `history/<slug>.json` until `s/<sid>/season.json` exists for every archive
   season**: the page falls back to it when a season file is missing (it reads
   `seasons[].season_id`, `year`, `standings`, `leaders`). Likewise `careers/` and
   `season_index.json` are now read only as fallbacks when `people/<pid>.json` is
   missing; `search.json` only when `people_index.json` / `clubs_index.json` are
   missing. All four can be retired once the new files are complete. `search.json`
   is still read by the Compare page's pickers (they need a competition per player),
   so keep it until that page moves to the people index.
7. **`people_index.json` `nt_tid` / `nt` and `club_tid` / `club`** are what the club
   page uses to flag internationals in a squad (and clubs in a national team's
   call-up). Please fill them for every person who has them.
8. **Section 7 item 7 (club squads in competition pages)**: the competition dossier on
   the club page is now titled "Players in <competition>" and lists this season's lines
   in that competition (a player who left still has his minutes there); the current
   squad shown on the club page is `clubs/<tid>.json` `squad.players` only.
9. **Last edition**: the page hides the Probabilities, Market and History tabs for a
   `last_edition` competition even if `tabs` lists them, and shows the final's winner
   from `fixtures.json` (`round == "final"`). A `winner` on the competition entry would
   be cleaner.

---

## 9. As built (2 October 2026): settled details and answers to section 8

Where this section and sections 1-4 differ, this section is what the build writes.

- **No timestamps in shards.** `people/<pid>.json`, `clubs/<tid>.json` and
  `s/<sid>/season.json` carry no `updated_at`, so an unchanged rebuild leaves them
  byte-identical; the two indexes and `seasons.json` do carry one.
- **Team ids everywhere (8.1).** Standings rows, `leaders` rows (`tid` beside `team`)
  and `bracket` rows (`home_id`, `away_id`) carry ids. Archive spellings are matched
  to the stores' clubs ("Liverpool FC" -> Liverpool, "Brighton & Hove Albion" ->
  Brighton): exact name, then without club affixes (FC, AFC, CF, SC, ...), then the
  single club whose words contain the name's; never a guess between two. About 88% of
  archive standings rows match today; the rest are clubs no store has seen (old cup
  entrants) and fill as the past-results backfill and the archive's new `team_id`
  arrive.
- **Champions (8.2).** A cup's `champion` comes only from a decided final. A league's
  comes from the top of a single official or computed table of a finished season.
  Last-edition competitions carry `winner` {team, tid} on their `competitions.json`
  entry and in `seasons.json` (8.9).
- **Season `source` on person and club rows.** `live` only while the competition's
  current edition is in progress; a finished edition (World Cup 2026, Club World Cup
  2025, Euro 2024) is `store` on those rows. `seasons.json` keeps `source: "live"` on
  the newest row (its payloads are the existing ones) with `status` beside it.
- **Archive season rows** in `people/<pid>.json` use the same keys as `seasons` rows:
  `apps`, `starts`, `min`, `g`, `a`, `xg`, `xa`, `rt`, plus `comp` (null when the
  tournament is not one the site follows), `tournament`, `kind`, `scope`, `season`,
  `era`, `team`, `source: "archive"`.
- **`current` flags (follow-up 5).** Each `seasons` row of a person has `current`:
  true when the row's team is his current club (club rows) or his national team
  (international rows). Every row of every club competition's `players_live.json` has
  `current`: false when the player's current club is not the club the row is for (he
  has left; his minutes there stay).
- **`line`** (the competition's full season line) is on a `seasons` row only above 90
  minutes, without the identity keys already on the person (`player_id`, `name`,
  `team`, `position`, ...).
- **Results.** `apps[].res` and `clubs/<tid>.json` `matches[].res` are from the
  player's / club's side, the score after extra time; a shoot-out is appended:
  `"D 2-2, lost 2-4 pens"` (or `"won on pens"` when the shoot-out score is not yet
  stored). Club `matches[]` also carry `gf`, `ga`, `pens` (club's side first) and
  `through` (1/0) for knockout matches. W/D/L and points never count a shoot-out.
  Note: France 4-6 England (World Cup 3rd place, 18 Jul 2026) is the real score after
  90 minutes (Sofascore event 12813003: normal time 4-6, no penalties).
- **`matches[].model`** on club pages is the fixture's `{h, d, a}` from the fixture's
  home side, exactly as `fixtures.json` (8.3); it is present only for matches still to
  play.
- **`current_club`** follows 2.3. `profile` comes from the squads fetcher's departure
  lookups (`squads/store.json` `people`) or the archive's player details, whichever is
  newer than his last appearance. Herrera (82474): Boca's roster no longer lists him;
  his profile (Real Zaragoza) is recorded by the next hourly squads run.
- **Squads store** also holds `people` {pid: {team_id, team, name, fetched_at}} (where a
  departed player went) and `pending` (departures still to look up).
- **Past seasons with results but no archive table** have `source: "archive"`, a
  `fixtures` list and a computed table.

---

## 10. Audit (2 October 2026): what changed for a reader

- **Season labels follow the name.** `season` is the season the competition's name
  states ("UEFA Super Cup 2026", "Euro 2020", "Super Cup 22/23"), not Sofascore's
  `year` field; a qualifying competition is labelled by the tournament it leads to
  ("World Cup Qualification, CONMEBOL" -> "2026"). `era` still comes from the year.
  Two editions with one label (two Trophees des Champions named "2026") fall back to
  their years; if still alike, the older one reads "<label> (earlier)".
- **Champions.** A league's `champion` is the top of its table (a split league's
  championship round); a league "final" is a relegation or promotion play-off and
  crowns no one, except in Liga MX, MLS and the Argentine torneos, whose title is
  decided in a play-off. A final in a qualifying stage (the Club World Cup play-in)
  crowns no one.
- **`status: "last_edition"`** once nothing is left to play and the edition is
  decided: its final played, a super cup's one tie done; otherwise (no final in the
  store) after 30 days for a league or a qualifying competition and 120 days for a
  knockout cup, which can sit between rounds for months.
- **Club season rows.** A league row's `played`/`w`/`d`/`l`/`gf`/`ga` are its league
  phase (play-offs and relegation ties apart); an archive row has the table's
  `played` and no record. `stage` values add `runner-up`, `qualified` and `po-final`
  (a qualifying competition's play-off final), `r1`..`r8` (a national cup's numbered
  rounds), `q1`..`q4` (continental qualifying rounds) and `prelim`. Friendlies carry
  no position or points. A club in several blocks of an official table takes its
  position from its own zone or table, never from an aggregate (annual table,
  relegation averages).
- **`clubs/<tid>.json` `matches[].xg`** (the club's side first) from the store's team
  statistics; `squad.as_of` is the latest *played* match.
- **Past seasons.** A postponed or cancelled copy of a fixture played under another
  id is dropped; an official table gains W, D, L and goals when the season's results
  account for every club's games; an archive season with nothing to show (no table,
  results or leaders) is not listed.
- **People.** `current_club.name` is the registry's spelling; a season row carries the
  competition's `line` only when the line's minutes are that row's (a mid-season
  transfer has one line for two clubs); archive rows carry `tid` when one club matches
  the archive's spelling; shirt numbers come from club competitions only; every player
  a competition's `players_live.json` lists has a person file.

---

## 11. As built (15 October 2026): slimmer person files, the value payloads

### 11.1 `people/<pid>.json` is slimmer

The deployed site was 712 MB of GitHub Pages' 1 GB, with `data/people/` the fastest-growing part as
the past-seasons backfill fills in. Two things no page read were dropped:

- **`seasons[].line`** (section 9, "the competition's full season line") is no longer written. It was
  76 of the 142 MB. The person page's competition dossier reads the competition's own
  `players_live.json`, and a past season's lines are in `s/<sid>/season.json` `players`.
  `PERSON_LINES = True` in `analytics/unified.py` restores it.
- **`teams[<tid>]`** is now `{name}` plus `national: true` only for a national team. The crest path
  was the same `assets/crests/<tid>.png` in every file and the page derives it from the id;
  `national: false` was implied.

Result: `data/people/` went from 141.7 MB to 57.8 MB (23,691 files), and the deployed site from 712 MB
to 629 MB. Every other key is unchanged; `people.js` needed no change.

### 11.2 The value payloads (`data/value/`)

Written by `build_value_layer` in `scripts/build_site_all.py` (after the unified step; model in
`analytics/value.py`, payloads in `analytics/value_payloads.py`, method in `docs/MODELS.md` 11b).
About 8.5 MB in all. Column-oriented files have `fields` and `rows`, as `people_index.json`.

**`value/meta.json`**: `model` {`currency`, `weights[{key, label, component, sign, padj, weight}]`
(goals per action, the rating per rating point), `box_scale`, `rating_weight`, `lambda`, `fitted`,
`fit_matches`, `prior_minutes` 450, `proj_minutes` 900, `regular_minutes` 900, `replacement_pct` 20,
`window_days` 365}; `validation` {`ok`, `n_matches`, `n_test`, `folds`, `burn_in`, `first_test_day`,
`lambdas`, `r2{xgd, gd}{rating, team, box, value, rmse_home}`}; `reliability` {`n_players`,
`value_r`, `box_r`, `rating_r`}; `components` (the ten names of the `c` arrays: Shooting, Creating,
Progression, Passing, Ball security, Defending, Aerial, Goalkeeping, Rating, League); `roles`
{code: label}; `units[{key, label, roles}]`; `replacement` {role: gross value per 90};
`role_mean_rate`; `regulars` {role: n}; `ppg` {league: points per goal, `_pool`}; `comps` {slug:
{name, short, kind, scope, centre, offset, method, coverage?, n_bridge?, approximate?, ppg, floor,
tier, current, previous}}; `tiers`; `fvi` {minutes, years, discount, reference_raw, reference,
value_per_rating_point, ageing{age: rating change}, continuation{age: p}, market_value_spearman{n,
rho}, n_ageing_pairs}; `market_value` {n, source}; `windows` {league: {open, until | next, spans}};
`today`; `targets` {max_age, strength_margin, league_step, free_max_age, per_need, regular_share,
minutes_cap}; `counts`; `updated_at`.

**`value/players.json`**: one row per player with club minutes in the last 12 months or a line this
season. `fields`: `id` (pid), `name`, `age`, `nat`, `role` (GK, CB, FB, DM, CM, AM, W, ST, or DF, MF,
FW without a start), `tid`, `club` (the current club, UNIFIED_PAYLOADS 2.3), `league` (the club's
league this season), `min`, `apps` (last 12 months, club football), `gar90`, `gar`, `par`, `pct`
(among regulars of the role; null under 900 minutes), `proj` (projected GAR/90), `fvi` (fair value
index; null without an age or under 450 minutes), `mv` (Sofascore market value in EUR, reference
only; null when the archive does not hold it), `until` (contract end "YYYY-MM", Sofascore's), `free`
(1 when Sofascore lists "No team"), `rt` (minutes-weighted rating), `c` (per-90 components against
the role's regular average, in `components` order). Sorted by `gar90`.

**`value/lines.json`**: one row per player per competition this season, 90+ minutes. `fields`: `id`,
`comp`, `tid` (the club of his latest line there), `min`, `apps`, `gar90`, `gar`, `par` (with the
competition's points per goal), `pct` (within the competition and unit, over its minutes floor),
`role`, `prev90` (GAR/90 last season in the same competition with 450+ minutes, else null), `rt`, `c`.

**`value/club/<tid>.json`**: one file per club of a followed league (twelve pooled leagues and
Argentina; 266 on 15 October 2026; files of clubs that left are pruned). `tid`, `name`, `league`,
`league_name`, `season`, `as_of`; `pool` {strength, rank, xgd} or null; `units[{unit, label, rate
(minutes-weighted projected GAR/90), pct, rank, n, grade (A-E), slots (players a match), few (graded
on the squad's best: under 270 minutes this season), empty, evidence{component, delta}, depth[{id,
name, role, proj, min (this season at the unit), age}]}]` in the order GK, CB, FB, MID, ATT, ST;
`strengths`, `weaknesses` (three unit keys each); `targets` {weak unit: [{id, name, age, role, tid,
club, league, min, proj, gain90, gain_pts_rest, gain_pts_38, fvi, mv, until, free, club_strength,
hints[]}]}; `ppg`; `remaining` (league matches left, from the sensitivity file); `matches_per_season`;
`gd_per_delta`; `sensitivity` (whether the league file has this club); `window`.

### 11.3 `<league>/sensitivity.json`

Written by `write_sensitivity` inside `build_league` (and for Argentina after `build_liga`), never
failing the competition. `shifts` [-0.3, -0.15, 0, 0.15, 0.3] (log goal-rate units), `n_sims` 2000,
`seed`, `remaining`, `metrics` (`exp_pts`, `p_title`, `band:<key>` for each band, `p_playoffs`,
`p_cup` where the league has them; Argentina `band:libertadores`, `band:sudamericana`,
`band:relegation`, and `torneo`), `bands[{key, label, kind}]`, `teams` {club name: {gd_per_delta,
remaining, <metric>: [value at each shift]}}, `runtime_s`, `updated_at`. A finished season writes
`{"teams": {}, "note": ...}`. Club names are the competition's (`teams.json`).

## 12. As built (16 October 2026): transfers, fair fees, budgets, fantasy

Method: `docs/MODELS.md` 11c (transfers) and 11d (fantasy). Sizes on 16 October: `value/transfers.json`
2.1 MB, `value/players.json` 4.5 MB (was 3.6), `value/club/` 5.9 MB (was ~2), `fantasy/` 1.5 MB (14 files):
about +6 MB on the deployed site.

### 12.1 The transfer store (fetcher output; never loaded by the page, pruned from the deploy)

`data/transfers/store.json`, written by phase 4 of `scripts/fetch_sofascore_history.py`, committed by the
hourly task with the other stores:

```jsonc
{"transfers": {"3665958": {"i": 3665958, "p": "827679", "n": "Ezri Konsa", "ps": "D", "f": 40, "fn": "Aston Villa",
                           "t": 42, "tn": "Arsenal", "k": 3, "fee": 59600000, "d": "59.6M €", "ts": 1787270400}},
 "teams": {"42": {"fetched_at": "...", "n": 26, "name": "Arsenal"}},     // club lists fetched
 "players": {"934235": {"fetched_at": "...", "n": 1}},                   // player histories fetched
 "failed": {"t1044584": {"at": "...", "status": 404}},                   // no page: retried after 14 days
 "meta": {"updated_at": "...", "n_transfers": 12373, "source": "..."}}
```

`k`: 1 loan, 2 loan return, 3 permanent; `fee` absent when Sofascore publishes none; `cur` only when not
EUR. The squads store's player rows gained `mv` (Sofascore's proposed market value) and `mvc` (its
currency when not EUR), and the store a `failed` map (clubs without a squad page, retried after 14 days).

### 12.2 `value/meta.json`: new keys

- `fee`: `n_fees`, `n_with_value`, `min_fit`, `fitted`; when fitted `validation` {`folds`, `lambda`, `n`,
  `cv` {`model`, `value_age_only`, `baseline_median`: {`n`, `mdae_log`, `error_factor`, `within_50pct`,
  `r2_log`, `median_abs_eur`, `spearman`}}, `time_split` {`train_until`, `test_from`, `model`,
  `baseline_median`}} and `model` {`features` (the 14 names), `mean`, `sd`, `coef`, `intercept`, `lambda`,
  `sigma` (cross-validated residual sd of log fee), `n`, `unknown_xgd`}; else `reason`. Always
  `market_value_check` {n, spearman_fair_fee} and `market_value_check_v2` {n, spearman_v2}.
- `v2`: `draws`, `years`, `discount`, `season_minutes`, `var_within`, `sigma_age`, `avail_prior`,
  `avail_prior_matches`, `avail_concentration`, `ppg`.
- `budgets`: `target_window`, `previous_window`, `next_window`, `n_clubs`, `features`, `market_values`,
  `ok`, `r2_log_cv`, `spearman_cv`, `residual_quantiles` [10, 25, 75, 90%], `inside_25_75_cv`,
  `winter_ratio`, `coef`, `mean`, `sd`, `intercept`, `n_budgets` (or `reason`).
- `transfers`: `coverage` {`transfers`, `by_kind`, `clubs_fetched`, `clubs_followed`, `clubs_fetched_all`,
  `players_fetched`, `first_date`, `last_date`, `squads_with_mv`, `players_with_mv`, `store_updated`},
  `grades` {`n_buyer`, `n_seller`, `window_days`, `perf_minutes`, `price_minutes`, `free_ref`},
  `runtime_s`, `source`.
- `market_value.source` now names the squads store as well as the archive.

### 12.3 `value/players.json`, `value/club/<tid>.json`, `value/transfers.json`

- **`players.json`** gained seven fields at the end: `v2`, `v2lo`, `v2hi` (valuation v2: expected points
  above replacement over four seasons and its 10-90% band), `avail` (shrunk availability), `fee`,
  `feelo`, `feehi` (fair fee to a buyer like his own club, EUR, null without the fee model or under 450
  minutes). `mv` now prefers the squads store's value.
- **`club/<tid>.json`** gained `budget` {`summer` {mid, lo, hi, lo80, hi80}, `next` {window, mid, lo, hi},
  `complete` (its list is fetched), `squad_mv`, `squad_mv_n`, `squad_n`, `mv_pre`} (null when neither a
  model budget nor squad values exist) and `ledger` {`in`, `out`, `returns`: [{key, date, pid, name, role,
  age, club, club_name, kind, fee, fee_text, fair, grade, post_min, post_gar90, proj_pre}], `windows`:
  [{window, label, spend, income, net, n_in, n_out, undisclosed, loans_in, free_in, complete}],
  `last12` {spend, income, net, fair_in, fair_out, value_added, gar_in, gar_out}, `fetched`}; each target
  gained `fee`, `fee_lo`, `fee_hi` (to this buyer) and `afford` ("yes", "stretch", "no" or null).
- **`transfers.json`** (new): column-oriented `fields`/`rows`, one row per move involving a followed club in
  the last 400 days (plus any move the lists below refer to): `key`, `date`, `pid`, `name`, `age` (at
  the move), `role`, `from`, `from_name`, `to`, `to_name`, `kind` (fee, free, undisclosed, youth, loan,
  loan_end), `fee`, `fee_text`, `window`, `fair` (fair fee at the time), `pre_min`, `proj_pre`,
  `post_min`, `post_gar90`, `post_share`, `b_grade`, `b_score`, `s_grade`, `s_score`, `winner`,
  `from_league`, `to_league`; `best`, `worst` (20 keys each); `windows` {league: {window: {spend, income,
  net, n_in, n_fee_in, undisclosed_in, loans_in, free_in, top[keys], best[keys], spenders[[tid, spend,
  income]], sellers[...], label}}}; `coverage`; `fee_fitted`; `today`; `next_window`; `latest_summer`;
  `updated_at`.

### 12.4 `fantasy/meta.json` and `fantasy/<league>.json`

- **`meta.json`**: `scoring`, `price_ranges`, `price_power`, `budget`, `squad`, `per_club`, `horizon`,
  `bench_weight`, `leagues` [{slug, name, players, gameweeks, next}], `backtest` {`ok`, `rounds`,
  `player_rounds`, `mean_actual`, `methods` {model, std, last5, y365: {label, mae, rmse, bias,
  spearman_round_mean, top20_actual_mean, by_position, big5_mae}}, `calibration`, `calibration_note`,
  `runtime_s`}, `rates`, `official_data`, `today`, `runtime_s`, `updated_at`.
- **`<league>.json`** (13 leagues; files of leagues no longer built are pruned): `league`, `name`,
  `season`, `as_of`, `gameweeks` [{gw, label, start, end, n}] (six), `n_gameweeks`, `fields`/`rows`: `id`,
  `name`, `pos` (G/D/M/F), `tid`, `club`, `price`, `next`, `h5`, `ros`, `tier`, `e_min`, `p60`, `p_goal`,
  `p_ga`, `cs`, `season_pts`, `season_min`, `season_apps`, `season_xpts`, `form_pts`, `form_xpts`,
  `form_apps`, `value`, `next_parts` (the next gameweek's points by `parts`: app, goals, assists, cs, gc,
  saves, cards, og_pm, dc, bonus); `fdr` [{tid, club, gws: [[[opponent, home 1/0, xG for, xG against,
  attack rating 1-5, defence rating 1-5], ...] per gameweek], xg_for, cs_sum}]; `squad` {solver, cost,
  budget, horizon, xi, bench, captain, vice, xi_h5, xi_next, formation} (or {solver: "greedy...",
  squad}); `picks` {captain, differentials, value, sell, buy_low, sell_high, buys {G, D, M, F}} (player
  ids); `updated_at`.

## 13. As built (17 October 2026): one season model, coverage, year by year

Why: `docs/football_data_audit.md`. Where this section and the earlier ones differ, this one is what the
build writes. Everything earlier keeps its keys; the additions below are new keys.

### 13.1 The season key (`era`)

- **Two frames.** A split season runs July to June and reads `"2026/27"`; a calendar season is the year,
  `"2026"`. Calendar competitions: Brasileirão, MLS, Liga MX (both halves fall in their year), Argentina,
  Libertadores, Sudamericana, Recopa, CONCACAF Champions Cup, Leagues Cup, Campeones Cup, Club World Cup,
  Intercontinental Cup, Copa do Brasil, Supercopa do Brasil, Copa Argentina, Supercopa Argentina, US Open Cup,
  Campeón de Campeones (`CALENDAR_COMPETITIONS` in `analytics/unified.py`). Every other club competition is
  split. `frame_of(slug)` answers `"split"`, `"calendar"` or `"international"`.
- **An edition's `era`** comes from the median date of its matches in its competition's frame
  (`edition_era`), not from Sofascore's `year`: the Johan Cruijff Schaal of 2 August 2026 is 2026/27 (it was
  2025/26), the Supercopa "2027" of January 2027 is 2026/27. An archive-only edition (no dates) takes its label,
  a four-digit year in a split competition moved by the offset its dated editions show (the Supercopa: one
  year back), by default opening the season that starts that year (a summer super cup). International
  editions get the calendar year of their median date (the competition's own season picker).
- **International football has no season of its own.** A player's international appearances count in his own
  frame by date (`app_era`), the split year turning on 1 August so a June or July tournament closes the season
  it ends: Haaland's 2026 World Cup is in his 2025/26, a Flamengo player's in his 2026. The two world club
  competitions (Club World Cup, Intercontinental Cup) are treated the same way (`NEUTRAL_COMPETITIONS`), for
  players and on club pages (the club's frame is its home league's).
- **A player's frame** (`person_frame`) is his latest club league's (else latest club competition's, else
  his archive career's latest season label), calendar by default. National teams' pages use the calendar year.

### 13.2 `people/<pid>.json`

- `frame`: `"split"` or `"calendar"`.
- `seasons[]` is one row per (competition, edition, team, **season**): an international edition that spans two
  of a player's seasons (World Cup qualifying, the Nations League) is two rows with the same `sid`.
- `seasons[].coverage`: `"full"` (every finished match of that team in that edition has line-ups),
  `"partial"` (some do not: the row is a lower bound), `"none"`, or `"totals"` (Sofascore's season totals
  replaced a partial line-up record: see below). When not full: `cov` [matches with line-ups, the team's
  finished matches] and `gap`: `"backfill"` (the hourly fetch has the missing matches queued),
  `"unavailable"` (Sofascore has no line-ups for them: `detail_missing` final, 13.8) or `"outside"` (ties the
  fetch never asks for: a national cup's or a qualifying round's without a followed club).
- **Season totals for partial rows.** When the archive holds Sofascore's season statistics for the same
  edition (matched on the season id, `sid`), the row is the only one for that edition, its coverage is partial
  and the totals have more minutes, the row takes the totals (`apps`, `starts`, `min`, `g`, `a`, `xg`, `xa`,
  `rt`) with `coverage: "totals"` and `lineups` {apps, min} (what the line-ups alone gave). 1,228 rows on 17
  October 2026 (the profiled players: ~1,250 careers).
- `archive[]` rows now carry `sid` and `coverage: "totals"`; they are matched to store rows on `sid` (was the
  label) and never repeat one.
- `years[]` (new): year by year, newest first: {`era`, `rows` (season x competition rows in it), `apps`,
  `starts`, `min`, `g`, `a`, `xg`, `xa`, `rt` (minutes-weighted), `intl` {apps, min, g, a} (the international
  part; the club part is the rest), `teams` [club tids by minutes], `coverage` ("partial" when any row in it
  is a lower bound)}. Built from `seasons` + `archive`, so the competitions always add up to the season.
  Zero `xg`, `xa`, `starts` and empty `intl`, `teams` are left out.
- `career_gap` {`through`: era} (17 October 2026): the archive's career list for him was cut by the
  fetcher's old twelve-row cap, which could stop mid-season (Mbappe's stopped at the Champions League
  2023/24: no Ligue 1, Coupe de France or anything from 2022/23). That season and every older one may miss
  competitions, so their `years[]` rows read `coverage: "partial"`, `gap: "career"` until the backfill
  lists him again (`fetch_sofascore_history.py`: `needs_relist`, whole seasons for `PLAYER_YEARS`).
- `archive[]` rows match their club through the competitions' team registries as well as the folded name
  ("Paris Saint-Germain" -> PSG, 1644), narrowed to the competition's clubs when several match.
- `mv` (Sofascore's market value, EUR unless `mvc`), `until` (contract end, ISO date), `foot`: the squad list
  that counts for him first (`squads/store.json`), then the archive's profile.

### 13.3 `people_index.json`

`fields` gain `season` and `mv` at the end. `min` is now the minutes of the player's **current season in his
own frame, every competition** (the same number as his `years` row for that season: a European's 2026/27, a
Brazilian's 2026); it was each competition's current edition summed, which mixed 2026/27 with 2026.

### 13.4 `clubs/<tid>.json`

- `seasons[]` rows of live and store editions with finished matches carry `coverage` (player data for the
  club's matches), and `cov`, `gap` when not full. World club competitions fall in the club's frame by date.
- `years[]` (new): {`era`, `comps`, `played`, `w`, `d`, `l`, `gf`, `ga`, `record` ("partial" when an archive
  table without W-D-L is in the season), `won` [cups won]} from the `seasons` rows (a league row is its league
  phase, as before).
- `squad.players[]` gain `mv` (`mvc`) and `until`.

### 13.5 `<slug>/seasons.json`, `s/<sid>/season.json`

- Store and live rows of `seasons.json` carry `coverage` (the edition's finished matches with line-ups) and
  `unavailable` (how many Sofascore has none for) when any.
- `season.json` carries `coverage`; `detail_matches` is the matches with line-ups; `fixtures[].detail` now
  means "has a match page" (13.6).

### 13.6 Match pages

`<slug>/matches/<id>.json` is written for every match of the live edition and for earlier matches from the
last 365 days (`has_match_page` in `build_site_all.py`, `MATCH_PAGE_DAYS`). The previous season is now fetched
in full (13.8) for the totals; a page for each of its ~4,000 older matches would add ~75 MB, so they feed the
people, clubs and season payloads only. `clubs/<tid>.json` `matches[].detail` and `season.json`
`fixtures[].detail` follow the same rule; the person page links a match only under it.

### 13.7 Leaderboards

- `players_live.json` `minutes_floor` (and `qualified`, the percentiles) is 30% of the minutes the
  competition's season has offered so far, at least 90 (`FLOOR_SHARE`, `FLOOR_MIN`; was 35% capped at 270):
  docs/MODELS.md 11.1.
- `players_global.json`: one window, the edition of the season under way in each competition's frame
  (`in_current_window`; an international competition while it has played in the last 60 days); every row is
  over its own competition's floor, so the pool floor (`minutes_floor`) is 90. New keys: `floor_share`,
  `floor_rule`, `left_out` (competitions whose built edition is not this season's), and `season` on each row.
- Unchanged: `value/players.json` (last 365 days of club football, its own 450/900-minute floors) and
  `players_lab_365.json` / `players_lab_ytd.json` (rolling windows of equal length for every player).
- Superseded on 21 October 2026 by `data/lab/` (section 14): one row per person in every view.

### 13.8 Stores: `detail_missing`

A competition store may hold `detail_missing` {gid: {`at`, `n`, `why`: "no-lineups" | "no-stats", `final`}},
written by `scripts/fetch_sofascore_leagues.py`: a match Sofascore answered without line-ups is asked again
after 1, then 7 days; on the third such answer it is `final` and never asked again. The fetch now queues
every finished match of every season the store holds (the previous season in full, not the last 365 days),
in tiers: the current season's new matches, its old-format ones, then the previous seasons of the followed
leagues, of the continental cups, of the rest; a backfilled match is three calls (line-ups, team statistics,
incidents; no shot map or momentum).

---

## 14. As built (21 October 2026): one row per person everywhere

Why: the cross-competition lists were one row per player per competition. Lionel Messi was seven dots in the
Player lab (MLS, Leagues Cup, Champions Cup, Campeones Cup, Club World Cup, World Cup, CONMEBOL qualifying), the
global leaderboard listed 1,609 players more than once, the value page's "this season" view 4,542, the players
page's rating card had Messi twice, and `players_lab.json` "this season" still carried finished editions (Copa
America 2024, the 2026 World Cup) because it read every built competition. Every such list is now one row per
person, keyed by Sofascore player id, with an explicit scope.

### 14.1 `data/lab/` (new; replaces `players_lab*.json` and `players_global.json`)

Written by `analytics/people_lines.py` (`PeopleLines`) inside `build_unified`: the same store loop as the
registry, each player-match added to compact accumulators keyed (person, competition, season tag), finalised by
`players.finalize_player` (the competition pages' own arithmetic: a one-competition line equals that
competition's `players_live.json` line).

- **Windows.** `season`: the player's current season in his own frame (13.1: a European's 2026/27, a
  Brazilian's 2026), the same season as his `years[0]` and `people_index.json` `min`; `last`: the season
  before; `365`: the last twelve months; `ytd`: the calendar year so far. A club edition counts in its own
  season (`season_meta` era); an international or world-club match counts in the player's frame by date (13.1).
- **Scopes.** `all` (every competition), `club` (club competitions), `intl` (national-team football), or a
  competition slug.
- `lab/<window>/<scope>.json`: {`window`, `scope`, `floor`, `fields`, `rows`}, one row per person with 90+
  minutes in the view. `fields`: `player_id`, `name`, `team` and `tid` (his current club, 2.3, for `all` and
  `club`; the national team for `intl`; the team he played for in a single competition), `position`, `age`,
  `minutes`, `matches`, `mix` ("MLS 2360' · World Cup 740' · ..."), `factor` (the pooled scoring factor,
  minutes-weighted over the competitions he played), `comp` (his main competition: most minutes, a club one
  first for `all`), then every rate of the catalogue (`lab_keys()`). `floor` is 30% of the minutes the view's
  regulars have played (its 95th percentile), at least 90: the default ranking floor of the view.
- `lab/index.json`: `windows` [{key, label, eras {split, calendar} | start, end}], `scopes` {window: {scope:
  {n, floor}}}, `scope_labels`, `comps` {slug: {name, short, kind, scope, factor, first_detail}}, `fields`,
  `metrics` (catalogue entries with `pct` and `lower`), `adjusted_keys`, `min_minutes`, `rule`, `updated_at`.
- `lab/leaders.json`: this season's top 15 by goals (with xG), assists (with xA) and rating (450+ minutes)
  for `all`, `club` and `intl`: {id, name, team, tid, comp, mix, value, minutes}.
- About 79 MB in 221 files on 21 October 2026 (the four retired files were 44 MB). The build deletes
  `players_lab.json`, `players_lab_365.json`, `players_lab_ytd.json` and `players_global.json` from the data
  directory after writing `lab/` (CI's restore step would otherwise copy the deployed ones back for ever).
  `build_global` writes `pool.json` only.

### 14.2 Front end

- **Player lab** (`#/lab/<all|club|intl|slug>/<pos>?w=season|last|365|ytd`): Season and Competitions pickers;
  one dot per player. Old `#/lab/<slug>/<pos>` links are the single-competition scope.
- **Leaders** (`#/players/leaders?w=&c=&m=&pos=&min=`): the same views; percentiles against the players shown;
  league-adjusted rates are the row's rate times its `factor`.
- **Players page** leader cards: `lab/leaders.json`, with an All / Club / National team switch.
- **Compare players** (`#/compare/players/<a>/<b>?scope=`): "Compare on" All competitions (default), Club
  competitions, National team (rows of `lab/season/<scope>.json`, percentiles against the same position in that
  view over its floor, at most 450), or one competition (its `players_live.json`, as before; an old
  `<comp>:<id>` key means that competition).
- **Value, this season** (`#/value?v=season&c=`): All competitions (default), Club competitions and National
  team sum each player's `value/lines.json` lines into one row (minutes, GAR and PAR add; GAR/90 is their ratio;
  rating and components minutes-weighted; percentile against the same unit among the rows shown with 900+
  minutes); a competition shows its own lines.
- `hub.json` `leaders` (each player's best competition line) and `search.json` `players` (his competition with
  most minutes, the others in `comps`) are one row per player too; nothing on the page reads `search.json` now.
- Unchanged and already one row per person: search and the compare pickers (`people_index.json`),
  `value/players.json`, club squads (`clubs/<tid>.json`). Per-competition by design: a competition's player
  tables and fantasy lists.

### 14.3 Duplicate Sofascore ids of one person

Sofascore sometimes lists one player under two ids (a roster copy beside the senior record). Rule
(`unified.same_person_aliases`, `MERGE_RULE`): two ids are one person only when the **exact name, date of birth
and nationality** are all present and all equal, and the two ids never appear in the same line-up. The id kept
has the most minutes, then the most appearances, then an archive career, then the lower number. A common name
with one birth date in two countries (Omar Ali, Qatar and Ghana, 1992-10-10) stays two people. On 21 October
2026 the rule merged 12 pairs (Luis Gabriel Rey, Kamika, Issah Haruna, Salman Al-Jadani, Diogo Pimentel, Antonio
Ceza, Romain Oller, Vachagan Danielyan, Carlos Barrio, Carlos Herrera, Jordan Hodkin, Sebastian Calabrese);
almost all were a roster-only copy with no minutes.

### 14.4 What a merge writes

- The alias's appearances, identity gaps, roster entry (the fresher one) and archive career (when the person
  has none) go to the person; `people_index.json` lists the person once and gains `aliases` {alias: person} and
  `merge_rule`.
- `people/<alias>.json` is a stub {`id`, `merged_into`, `name`}; the person page redirects to the person, and
  `FB.peopleIndex().byId[alias]` is the person's row.
- A club squad lists the person once; the lab lines add the alias's matches to the person's.
- The value layer (`analytics/value*`) still keys its rows by the id it saw; the value page's season view folds an
  alias into the person when the people index is already loaded. Aliases are roster copies with almost no
  minutes, so this has not yet mattered.

### 14.5 The Argentine archive year

The Argentine store keys its seasons by torneo (`2026-apertura`, `2026-clausura`), so the archive's whole-year
edition (Sofascore season 87913, "2026") never matched a store row on its id and was added on top: 55 players
had their 2026 counted twice (Nahuel Losada 5,790 minutes for 3,450 played). An archive Argentine league season
in a year the store holds is now the store's.

## 15. As built (23 October 2026): who moves next (`value/moves.json`, clubs' `movement`)

Code: `oddsmarkets/football/analytics/moves.py`, called by `build_movement` in `value_payloads.py` inside the
value step (about 8 seconds a build). Method and validation: `docs/MODELS.md` 11e and
`docs/research/football_moves.md`. No field of an existing payload was renamed; the club files gain one key.

### 15.1 `value/moves.json` (new, about 0.9 MB)

`{"fields", "rows", "meta", "updated_at"}`, one row per player of a followed league's club who played for it in the
last 180 days (about 7,500), most likely to leave first:

| Field | Meaning |
|---|---|
| `id`, `tid` | Sofascore player id (string), his club |
| `p` | chance he leaves the club in the coming window (`meta.horizon`): a **base rate**, see `basis` |
| `basis` | `league_band` (his league x role band in the reference window), `loan` (his region's on-loan rate), `region` (no window of this kind for his league yet: Liga Argentina) |
| `band` | `regular` (50%+ of the club's minutes since he joined it), `rotation` (20-50%), `fringe` |
| `loan` | 1 when his latest move into the club was a loan |
| `share` | his share of the club's minutes since he joined it (last 12 months, capped at 1) |
| `types` | if he moves: chance of each of `meta.types` (`transfer`, `free`, `loan`, `loan_end`, `release`); sums to 1 |
| `dests` | if he moves: chance of each of `meta.dests` (`same` league, `stronger`, `weaker`, `outside` our leagues); sums to 1 |
| `p_club` | chance he joins another club of our leagues in the window (`p` x not a release or loan end x not outside) |

`meta`: `ok` (false with `reason` when nothing could be built), `method` (the Model page's text), `horizon`
("Winter 2026/27"), `horizon_start`, `today`, `windows` (the labelled windows: `window`, `n`, `rate`),
`reference` (the base-rate table: `window`, `overall`, `region`, `league` {slug: {rate, n}}, `cell`
{"slug|band": {rate, n}}, `loan` {region: {rate, n}}), `validation` (the pre-registered test's numbers, fixed:
`leave`, `type`, `dest`, `arrivals`, `targets`, `choice`, each with `passed`), `types`, `type_labels`, `dests`,
`dest_labels`, `units` (G/D/M/F names), `bands`, `models` (the type, destination and destination-club models'
coefficients), `arrivals` (`window`, `mean_per_club`, `mix` by unit), `n_players`, `n_clubs`, `runtime_s`.

### 15.2 `value/club/<tid>.json`: `movement` (new key, about 4 KB a club)

```
"movement": {
  "horizon": "Winter 2026/27",
  "basis": {"leave": "base_rate", "window": "Winter 2025/26", "arrivals": "league" | "region", "arrivals_clubs": n},
  "expected_out": {"G","D","M","F": players expected to leave (sum of the players' p)}, "out_total",
  "expected_in": {"G","D","M","F": expected arrivals (the reference window's arrivals per club in the league x its unit mix)}, "in_total",
  "p_add": {"G","D","M","F": chance of adding at least one there (1 - exp(-expected_in))},
  "roster": [[pid, p, most likely type]],                # every player in the population, most likely to leave first
  "targets": [{"id","name","tid","club","league","unit","role","age",
               "p_join",                                  # chance he joins this club in the window (the rank)
               "p_move","p_club",                         # his chance of leaving; of joining any club of our leagues
               "plaus",                                   # this club's share of his likely destinations x the number of clubs (1 = an average club)
               "q_gap",                                   # his match rating (shrunk) minus the club's minutes-weighted rating at his unit
               "need",                                    # the club's expected departures at his unit / its usual starters there
               "proj","fee","afford",                     # projected GAR/90; fair fee to this club and budget fit, as `targets`
               "why"}]                                    # one line: role at his club, league step, loan, rating gap
} | null                                                  # null: the club has no player in the population
```

Targets are players who would improve the club (450+ minutes for their club in 12 months, `q_gap` >= 0) and leave
out a player whose fair fee to the club is over 1.5 x its 90th-percentile summer budget (as the existing `targets`). The existing `targets` (by weak unit, on value) are unchanged; `movement.targets` is the
movement-based list.

## Metrics-spec fields (23 Oct 2026)

- `<slug>/players_live.json` players[]: `role` (the value model's formation role of his line in that competition: GK,
  CB, FB, DM, CM, AM, W, ST; DF / MF / FW for substitute-only lines; else his 12-month role) and `gar90` (goals added
  above replacement per 90 in that competition, from `value/lines.json`; null under 90 minutes there).
- `lab/<window>/<scope>.json`: `role` and `gar90` appended to `fields` (earlier column positions unchanged). The
  "season" window of one competition reads that line; other windows and scopes read the 12-month value
  (`value/players.json`).
- `people/<pid>.json` `role`: the 12-month formation role (absent when the value model has no line for him).
- `people_names.json`: the search index, names only: `fields` [id, name, pos, club], `rows`, `aliases` (about 0.5 MB
  gzipped against 1.1 MB for `people_index.json`).
- `pool.json` clubs[]: `rated` (in a followed league or with league-table games: the clubs the pages list) and
  `rank_rated` (rank by strength among rated clubs; null otherwise); `model.n_rated`. Club files
  (`clubs/<tid>.json` and `value/club/<tid>.json`) `pool` gain `rank_rated` and `rated`.
- Written by `oddsmarkets/football/analytics/value_fields.py` after the value layer (players_live, lab, changed
  people roles) and by the unified step (people roles from the value files on disk, people_names.json).
