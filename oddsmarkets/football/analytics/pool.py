"""
The cross-competition scale: every club on one Dixon-Coles surface, and what it
implies for comparing leagues and players.

The pooled fit (`build_site_all.fit_pooled`) estimates attack and defence for
every club under a `<league>:<club>` prefix, with the cups' matches as the
bridge between leagues. This module reads those parameters back into:

- a club table: attack, defence and expected points per game against the
  pool-average club at a neutral venue (the same "strength" the power rankings
  use, now on one scale for every club);
- league aggregates: the mean attack and defence of a league's clubs, and a
  scoring factor — how much easier it is to score against that league's
  defences than against the pool average — used to put players' attacking
  rates from different leagues on one footing;
- a hypothetical match between any two clubs, which the front-end computes
  from the same parameters.

The adjustment is a flat per-league factor from the pooled model. It is honest
about what the data supports and no more: it corrects for the quality of the
opposition a player's numbers were produced against, not for tactical roles,
squad quality or minutes. A league connected to the pool by few cup matches
(MLS, the Saudi league, the AFC's non-Saudi clubs) has a less certain factor,
and `connection` says how many bridging matches there are.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.stats import poisson

MAX_GOALS = 8

# Continental blocks. Within a block the cups play the clubs against each other
# every week and the scale is well identified; between blocks only the
# Intercontinental Cup and the Club World Cup bridge, so a cross-block
# comparison rests on a handful of matches and the front-end says so.
BLOCKS = {
    "premier-league": "Europe", "la-liga": "Europe", "serie-a": "Europe", "bundesliga": "Europe", "ligue-1": "Europe",
    "eredivisie": "Europe", "primeira-liga": "Europe", "belgian-pro-league": "Europe",
    "champions-league": "Europe", "europa-league": "Europe", "conference-league": "Europe",
    "brasileirao": "South America", "liga-argentina": "South America", "libertadores": "South America", "sudamericana": "South America",
    "mls": "North America", "liga-mx": "North America", "concacaf-champions-cup": "North America",
    "saudi-pro-league": "Asia", "afc-champions-league": "Asia",
    "caf-champions-league": "Africa",
    "intercontinental-cup": "World", "club-world-cup": "World",
}

# Attacking rates that get a league-adjusted twin (`<key>_adj`).
ADJUSTED_KEYS = (
    "goals_90", "npg_90", "assists_90", "xg_90", "npxg_90", "xa_90", "xgot_90",
    "shots_90", "key_passes_90", "big_chances_90",
)


def dc_score_matrix(att_h: float, def_h: float, att_a: float, def_a: float, rho: float,
                    home_adv: float = 0.0, max_goals: int = MAX_GOALS) -> np.ndarray:
    """The Dixon-Coles score matrix for one match (rows home goals, columns away)."""
    lam_h = math.exp(att_h + def_a + home_adv)
    lam_a = math.exp(att_a + def_h)
    k = max_goals + 1
    ph = poisson.pmf(np.arange(k), lam_h)
    pa = poisson.pmf(np.arange(k), lam_a)
    m = np.outer(ph, pa)
    m[0, 0] *= 1 - lam_h * lam_a * rho
    m[1, 0] *= 1 + lam_a * rho
    m[0, 1] *= 1 + lam_h * rho
    m[1, 1] *= 1 - rho
    m = np.maximum(m, 0)
    total = m.sum()
    return m / total if total > 0 else m


def outcome_probs(m: np.ndarray) -> tuple[float, float, float]:
    return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


def club_params(pooled) -> dict[tuple[str, str], dict[str, float]]:
    """(prefix, club) -> {attack, defence} from the pooled fit's parameters."""
    out: dict[tuple[str, str], dict[str, float]] = {}
    for key, value in pooled.params_.items():
        for kind, field in (("attack_", "attack"), ("defense_", "defence")):
            if key.startswith(kind) and ":" in key:
                prefix, club = key[len(kind):].split(":", 1)
                out.setdefault((prefix, club), {"attack": 0.0, "defence": 0.0})[field] = float(value)
                break
    return out


def build_pool(pooled, league_names: dict[str, str], cup_names: dict[str, str],
               strength_rows: dict[str, dict[str, dict]] | None = None,
               teams_info: dict[str, dict[str, dict]] | None = None,
               connections: dict[str, int] | None = None, bridges: dict[str, int] | None = None) -> dict[str, Any]:
    """
    The cross-competition payload: every club's pooled parameters and strength,
    per-league aggregates and scoring factors, and the model constants the
    front-end needs to price a hypothetical match.
    """
    params = pooled.params_
    rho = float(params.get("rho", 0.0))
    home_adv = float(params.get("home_adv", 0.0))
    clubs = club_params(pooled)
    league_clubs = {k: v for k, v in clubs.items() if k[0] in league_names}
    if not league_clubs:
        league_clubs = clubs
    att_bar = float(np.mean([v["attack"] for v in league_clubs.values()]))
    def_bar = float(np.mean([v["defence"] for v in league_clubs.values()]))

    rows = []
    for (prefix, club), p in clubs.items():
        m = dc_score_matrix(p["attack"], p["defence"], att_bar, def_bar, rho)
        h, d, a = outcome_probs(m)
        lam_for = math.exp(p["attack"] + def_bar)
        lam_against = math.exp(att_bar + p["defence"])
        extra = ((strength_rows or {}).get(prefix) or {}).get(club) or {}
        info = ((teams_info or {}).get(prefix) or {}).get(club) or {}
        rows.append({
            "team": club, "comp": prefix, "comp_name": league_names.get(prefix) or cup_names.get(prefix) or prefix,
            "in_league": prefix in league_names,
            "attack": round(p["attack"], 4), "defence": round(p["defence"], 4),
            "xg_for": round(lam_for, 3), "xg_against": round(lam_against, 3),
            "strength": round(3 * h + d, 4), "p_win_avg": round(h, 4), "p_draw_avg": round(d, 4),
            "elo": extra.get("elo"), "table_rank": extra.get("table_rank"), "played": extra.get("played"),
            "ppg": extra.get("ppg"), "form_results": extra.get("form_results"), "xg_diff": extra.get("xg_diff"),
            "luck": extra.get("luck"), "team_id": info.get("team_id"), "crest": info.get("crest"),
            "slug": info.get("slug"),
        })
    rows.sort(key=lambda r: -r["strength"])
    n_rated = 0
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
        # rated: a club of a followed league, or one with league-table games this season (the clubs the pages list); the
        # rest (lower-division cup entrants, about 1,300) carry ratings that lean on the cup tier prior. rank_rated ranks
        # the rated clubs only, so pages need not filter and re-rank.
        r["rated"] = bool(r["in_league"] or (r.get("played") or 0) > 0)
        if r["rated"]:
            n_rated += 1
        r["rank_rated"] = n_rated if r["rated"] else None

    leagues: dict[str, dict] = {}
    for slug, name in league_names.items():
        members = [r for r in rows if r["comp"] == slug]
        if not members:
            continue
        mean_att = float(np.mean([r["attack"] for r in members]))
        mean_def = float(np.mean([r["defence"] for r in members]))
        leagues[slug] = {
            "name": name, "n_clubs": len(members),
            "attack": round(mean_att, 4), "defence": round(mean_def, 4),
            "strength": round(float(np.mean([r["strength"] for r in members])), 4),
            "best": members[0]["team"], "best_rank": members[0]["rank"],
            # Scoring against this league's defences relative to the pool average:
            # a rate produced here is multiplied by this to compare across leagues.
            "factor_att": round(math.exp(def_bar - mean_def), 4),
            # And conceding to its attacks, for defensive context.
            "factor_def": round(math.exp(att_bar - mean_att), 4),
            "connection": int((connections or {}).get(slug, 0)),
        }
    order = sorted(leagues, key=lambda s: -leagues[s]["strength"])
    for i, slug in enumerate(order, start=1):
        leagues[slug]["rank"] = i
        leagues[slug]["block"] = BLOCKS.get(slug, "Other")
    for r in rows:
        r["block"] = BLOCKS.get(r["comp"], "Other")
    return {
        "model": {"rho": round(rho, 5), "home_adv": round(home_adv, 5), "attack_mean": round(att_bar, 5),
                  "defence_mean": round(def_bar, 5), "max_goals": MAX_GOALS, "n_clubs": len(rows), "n_rated": n_rated},
        "leagues": leagues,
        "clubs": rows,
        "bridges": bridges or {},
    }


def block_bridges(cup_frames: dict[str, Any]) -> dict[str, int]:
    """
    Matches between clubs of different continental blocks, per block pair
    ("Europe|South America": n). These are the only evidence the pooled fit has
    for the level of one block against another.
    """
    counts: dict[str, int] = {}
    for df in cup_frames.values():
        if df is None or not len(df):
            continue
        for h, a in zip(df["home_team"], df["away_team"]):
            bh = BLOCKS.get(str(h).split(":", 1)[0], "Other")
            ba = BLOCKS.get(str(a).split(":", 1)[0], "Other")
            if bh != ba:
                key = "|".join(sorted((bh, ba)))
                counts[key] = counts.get(key, 0) + 1
    return counts


def adjust_players(players: list[dict], factor_of_comp: dict[str, float]) -> None:
    """Write the league-adjusted twins of the attacking rates onto each player row (in place)."""
    for p in players:
        f = float(factor_of_comp.get(p.get("comp") or "", 1.0))
        p["adj_factor"] = round(f, 4)
        for key in ADJUSTED_KEYS:
            v = p.get(key)
            if v is not None:
                p[key + "_adj"] = round(float(v) * f, 3)


def connections_from_frames(cup_frames: dict[str, Any], league_slugs: list[str]) -> dict[str, int]:
    """How many cup matches involve each league's clubs (the strength of its bridge to the pool)."""
    counts = {s: 0 for s in league_slugs}
    for df in cup_frames.values():
        if df is None or not len(df):
            continue
        for col in ("home_team", "away_team"):
            for name in df[col]:
                prefix = str(name).split(":", 1)[0]
                if prefix in counts:
                    counts[prefix] += 1
    return counts
