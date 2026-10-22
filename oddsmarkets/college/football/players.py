"""
Player value for college football: EPA above replacement for the skill positions (from the plays), box-score
points for defence and specialists, team units (strengths and needs), inferred transfers, suggestions.

Attribution: the passer, the target and the ball carrier of each pass/rush snap are parsed from ESPN's play text
("#11 C.Beck pass complete short right to #10 M.Toney ...", "Jaxson Dart pass complete to Cayden Lee for 28 yds",
"Jordan James run for 8 yds") and matched to the players in that game's box score for the offence by first
initial + surname (suffixes dropped), then surname alone when unique. Unmatched names get no credit.

Skill value (garbage time excluded): passer = EPA of his dropbacks (completions, incompletions, sacks,
interceptions); ball carrier = EPA of his rushes; target = EPA of the passes thrown to him. Position value:
QB = dropbacks + rushes; RB = rushes + targets; WR/TE = targets + rushes. Replacement level per position = the
EPA per play of the non-starters (players outside each team's top QB 1 / RB 2 / WR 3 / TE 1 by snaps), and
value = EPA - replacement rate x plays (points above a replacement-level player given the same plays).

Defence and specialists (box score, points; documented weights):
  solo tackle 0.25, assisted tackle 0.12, tackle for loss +0.9, sack +1.0 (on top of its TFL), pass defended 0.7,
  QB hurry 0.35, interception 3.5, defensive TD 4.0; kicking 3 x (FG made - 0.78 x FG att) + (XP made - 0.96 x XP att);
  punting 0.035 x (gross average - 41.5) x punts + 0.25 x inside the 20 - 0.1 x touchbacks; returns 0.03 x (kick
  return yards - 21 per return) + 0.05 x (punt return yards - 8 per return) + 3 per return TD.
  Defensive replacement = the per-game points of players outside each team's top DL 4 / LB 3 / DB 4; value =
  points - replacement x games.
Positions: the roster position (any season's store, the season's own first), else inferred from usage.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

from oddsmarkets.college import canon

from . import data

SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}
STARTERS = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "DL": 4, "LB": 3, "DB": 4, "K": 1, "P": 1}
SKILL = ("QB", "RB", "WR", "TE")
DEF = ("DL", "LB", "DB")
POS_ORDER = ("QB", "RB", "WR", "TE", "DL", "LB", "DB", "K", "P")
POS_LABEL = {"QB": "Quarterback", "RB": "Running back", "WR": "Wide receiver", "TE": "Tight end", "DL": "Defensive line",
             "LB": "Linebacker", "DB": "Defensive back", "K": "Kicker", "P": "Punter"}

_BOX_MAP = {
    "passing": {"cmp": "pass_cmp", "att": "pass_att", "passing_yards": "pass_yds", "passing_touchdowns": "pass_td",
                "interceptions": "pass_int"},
    "rushing": {"rushing_attempts": "rush_car", "rushing_yards": "rush_yds", "rushing_touchdowns": "rush_td"},
    "receiving": {"receptions": "rec", "receiving_yards": "rec_yds", "receiving_touchdowns": "rec_td"},
    "fumbles": {"fumbles_lost": "fum_lost"},
    "defensive": {"total_tackles": "tkl", "solo_tackles": "solo", "sacks": "sacks", "tackles_for_loss": "tfl",
                  "passes_defended": "pd", "hurries": "hurries", "qb_hits": "hurries", "defensive_touchdowns": "def_td"},
    "interceptions": {"interceptions": "def_int", "interception_yards": "def_int_yds", "interception_touchdowns": "def_int_td"},
    "kickReturns": {"kick_returns": "kr", "kick_return_yards": "kr_yds", "kick_return_touchdowns": "kr_td"},
    "puntReturns": {"punt_returns": "pr", "punt_return_yards": "pr_yds", "punt_return_touchdowns": "pr_td"},
    "kicking": {"fgm": "fgm", "fga": "fga", "xpm": "xpm", "xpa": "xpa", "long_field_goal_made": "fg_long"},
    "punting": {"punts": "punts", "punt_yards": "punt_yds", "punts_inside20": "punt_in20", "touchbacks": "punt_tb"},
}
STAT_COLS = sorted({v for m in _BOX_MAP.values() for v in m.values()})


# ── names ───────────────────────────────────────────────────────────────────

def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z\s.'-]", "", s.lower())


def name_key(name: str) -> tuple[str, str] | None:
    """(first initial, surname) from 'Carson Beck', 'C.Beck', 'M.Fletcher Jr.', 'Johntay Cook Ii'."""
    s = _fold(name).replace("'", "").replace("-", " ").strip()
    if not s or s.startswith("team"):
        return None
    if "." in s.split(" ")[0] and len(s.split(".")[0]) <= 2:
        first, rest = s.split(".", 1)
        toks = rest.replace(".", " ").split()
        first = first.strip()
    else:
        toks = s.replace(".", " ").split()
        if not toks:
            return None
        first, toks = toks[0], toks[1:]
    toks = [t for t in toks if t not in SUFFIX]
    if not toks or not first:
        return None
    return first[0], " ".join(toks)


_LEAD = re.compile(r"^\(\d+:\d+\)\s*")
_FORM = re.compile(r"^(?:no huddle-shotgun|no huddle|shotgun|pistol|under center|wildcat)\s+", re.IGNORECASE)
_NUM = re.compile(r"#\d+\s*")


def _clean_name(x: str) -> str:
    m = re.search(r"#(\d+)", x or "")
    name = _NUM.sub("", x).strip(" ,.;")
    return f"{name}|{m.group(1)}" if m else name


def parse(text: str) -> dict:
    """{"passer","target","rusher"} raw names from one play's text (None where absent)."""
    s = _LEAD.sub("", str(text or "")).strip()
    for _ in range(2):
        s = _FORM.sub("", s)
    out = {"passer": None, "target": None, "rusher": None}
    m = re.match(r"^(.+?)\s+(\d+)\s+yd pass from\s+(.+?)\s*(?:\(|$)", s, re.IGNORECASE)
    if m:
        out["target"], out["passer"] = _clean_name(m.group(1)), _clean_name(m.group(3))
        return out
    m = re.match(r"^(.+?)\s+\d+\s+yd run\b", s, re.IGNORECASE)
    if m:
        out["rusher"] = _clean_name(m.group(1))
        return out
    m = re.match(r"^(.+?)\s+(?:pass|sacked|scrambles?)\b", s, re.IGNORECASE)
    if m and not re.match(r"^(.+?)\s+(?:rush|run)\b", m.group(1), re.IGNORECASE):
        out["passer"] = _clean_name(m.group(1))
        t = re.search(r"\bpass (?:complete|incomplete|intercepted)?.*?\bto\s+(#\d+\s+)?([A-Z][^,()]*?)(?=\s+(?:for|caught|thrown|at|broken|is|was|out)\b|,|\(|$)", s)
        if t and not re.search(r"\bthrown to\b", s[: t.start() + 12] if False else ""):
            cand = _clean_name((t.group(1) or "") + t.group(2))
            if cand and not re.match(r"^(the|[A-Z]{2,5}\d*)$", cand):
                out["target"] = cand
        return out
    m = re.match(r"^(.+?)\s+(?:rush|run|scramble)\b", s, re.IGNORECASE)
    if m:
        out["rusher"] = _clean_name(m.group(1))
    return out


# ── box frame ───────────────────────────────────────────────────────────────

def box_frame(season: int, st: dict | None = None) -> pd.DataFrame:
    """One row per (gid, team, pid) with the box stats (STAT_COLS), game date and opponent."""
    st = st if st is not None else data.load_store(season)
    rows = []
    for gid, g in (st.get("games") or {}).items():
        box = g.get("box") or {}
        if not box or g.get("status") != "post":
            continue
        h, a = str(g.get("home")), str(g.get("away"))
        for tid, b in box.items():
            per: dict[str, dict] = {}
            for cat, block in ((b or {}).get("players") or {}).items():
                mp = _BOX_MAP.get(cat)
                if not mp:
                    continue
                cols = block.get("cols") or []
                for r in block.get("rows") or []:
                    if not r:
                        continue
                    pid = str(r[0])
                    if not data.real_team(pid):     # ESPN's team row (negative id, name "Team"): not a player
                        continue
                    d = per.setdefault(pid, {})
                    for j, c in enumerate(cols):
                        k = mp.get(c)
                        if k and j + 1 < len(r):
                            v = r[j + 1]
                            if isinstance(v, (int, float)) and np.isfinite(v):
                                d[k] = d.get(k, 0) + v if k != "fg_long" else max(d.get(k, 0), v)
            for pid, d in per.items():
                d.update({"gid": str(gid), "team": str(tid), "pid": pid, "date": g.get("date"),
                          "opp": a if str(tid) == h else h, "home": str(tid) == h, "stype": g.get("stype"),
                          "week": g.get("week")})
                rows.append(d)
    df = pd.DataFrame(rows)
    if not len(df):
        return pd.DataFrame(columns=["gid", "team", "pid", "date", "opp", "home"] + STAT_COLS)
    for c in STAT_COLS:
        if c not in df:
            df[c] = 0.0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


# ── attribution ─────────────────────────────────────────────────────────────

def attribute(pl: pd.DataFrame, box: pd.DataFrame, players: dict) -> pd.DataFrame:
    """passer_id / target_id / rusher_id per pass/rush snap of a plays frame (with epa)."""
    if not len(pl) or not len(box):
        return pl.assign(passer_id=None, target_id=None, rusher_id=None)
    idx: dict[tuple[str, str], dict] = {}
    for (gid, team), g in box.groupby(["gid", "team"], sort=False):
        full, last = {}, {}
        for pid in g["pid"]:
            nm = (players.get(pid) or {}).get("name")
            k = name_key(nm) if nm else None
            if not k:
                continue
            full.setdefault(k, []).append(pid)
            last.setdefault(k[1], []).append(pid)
        idx[(gid, team)] = {"full": full, "last": last}

    def match(gid, team, raw):
        if not raw:
            return None
        raw, _, num = raw.partition("|")
        k = name_key(raw)
        if not k:
            return None
        ix = idx.get((gid, team))
        if not ix:
            return None
        c = ix["full"].get(k)
        if c and len(c) == 1:
            return c[0]
        if c and num:
            j = [p for p in c if str((players.get(p) or {}).get("jersey") or "") == num]
            if len(j) == 1:
                return j[0]
        c2 = ix["last"].get(k[1])
        if c2 and len(c2) == 1:
            return c2[0]
        return None

    s = pl["scrim"].to_numpy(bool)
    pas, tgt, rus = [None] * len(pl), [None] * len(pl), [None] * len(pl)
    texts, gids, offs = pl["text"].to_numpy(), pl["gid"].to_numpy(), pl["offense"].to_numpy()
    for i in np.flatnonzero(s):
        p = parse(texts[i])
        if p["passer"]:
            pas[i] = match(gids[i], offs[i], p["passer"])
        if p["target"]:
            tgt[i] = match(gids[i], offs[i], p["target"])
        if p["rusher"]:
            rus[i] = match(gids[i], offs[i], p["rusher"])
    out = pl.copy()
    out["passer_id"], out["target_id"], out["rusher_id"] = pas, tgt, rus
    return out


# ── positions ───────────────────────────────────────────────────────────────

def position_map(seasons: list[int]) -> dict[str, str]:
    """pid -> roster position pool from the stores (later seasons override earlier)."""
    out: dict[str, str] = {}
    for s in sorted(seasons):
        st = data.load_store(s)
        for pid, p in (st.get("players") or {}).items():
            pp = canon.pool("cfb", p.get("pos"))
            if pp and pp not in ("OL", "ATH"):
                out[pid] = pp
            elif pp == "OL":
                out[pid] = "OL"
    return out


def infer_pos(r: pd.Series) -> str:
    if r.get("pass_att", 0) >= 8 and r.get("pass_att", 0) >= r.get("rush_car", 0):
        return "QB"
    off = r.get("rush_car", 0) + r.get("rec", 0) + r.get("tgt", 0)
    de = r.get("tkl", 0) + r.get("pd", 0) + r.get("sacks", 0)
    if r.get("fga", 0) + r.get("xpa", 0) > 0 and off + de < 3:
        return "K"
    if r.get("punts", 0) > 0 and off + de < 3:
        return "P"
    if off >= de and off > 0:
        return "RB" if r.get("rush_car", 0) > r.get("rec", 0) + r.get("tgt", 0) * 0.5 else "WR"
    if de > 0:
        pas = r.get("pd", 0) + r.get("def_int", 0)
        rush = r.get("sacks", 0) + r.get("tfl", 0) + r.get("hurries", 0)
        if pas >= max(rush, 1):
            return "DB"
        if rush >= 2 * max(pas, 0.5):
            return "DL"
        return "LB"
    return "WR"


# ── season value ────────────────────────────────────────────────────────────

def def_points(df: pd.DataFrame) -> pd.Series:
    ast = (df["tkl"] - df["solo"]).clip(lower=0)
    return (0.25 * df["solo"] + 0.12 * ast + 0.9 * df["tfl"] + 1.0 * df["sacks"] + 0.7 * df["pd"] + 0.35 * df["hurries"]
            + 3.5 * df["def_int"] + 4.0 * (df["def_td"] + df["def_int_td"]))


def st_points(df: pd.DataFrame) -> pd.Series:
    k = 3 * (df["fgm"] - 0.78 * df["fga"]) + (df["xpm"] - 0.96 * df["xpa"])
    avg = np.where(df["punts"] > 0, df["punt_yds"] / df["punts"].clip(lower=1), 41.5)
    p = 0.035 * (avg - 41.5) * df["punts"] + 0.25 * df["punt_in20"] - 0.1 * df["punt_tb"]
    r = 0.03 * (df["kr_yds"] - 21 * df["kr"]) + 0.05 * (df["pr_yds"] - 8 * df["pr"]) + 3 * (df["kr_td"] + df["pr_td"])
    return k + p + r


def play_credit(pa: pd.DataFrame) -> pd.DataFrame:
    """Per (gid, pid): dropbacks, dropback EPA, rushes, rush EPA, targets, target EPA (garbage time excluded)."""
    s = pa[pa["scrim"] & ~pa["garbage"] & np.isfinite(pa["epa"].to_numpy(float))]
    parts = []
    for col, kind, pre in (("passer_id", "pass", "db"), ("rusher_id", "rush", "ru"), ("target_id", "pass", "tg")):
        x = s[(s["kind"] == kind) & s[col].notna()]
        if not len(x):
            continue
        g = x.groupby(["gid", col]).agg(**{f"{pre}_n": ("epa", "size"), f"{pre}_epa": ("epa", "sum"),
                                           f"{pre}_succ": ("success", "sum")}).reset_index()
        parts.append(g.rename(columns={col: "pid"}))
    if not parts:
        return pd.DataFrame(columns=["gid", "pid"])
    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on=["gid", "pid"], how="outer")
    for c in out.columns:
        if c not in ("gid", "pid"):
            out[c] = out[c].fillna(0.0)
    return out


def season_value(season: int, box: pd.DataFrame, credit: pd.DataFrame, pos_map: dict[str, str], st: dict) -> pd.DataFrame:
    """One row per (pid, main team) for the season: stats, position, value, value per game, percentile, why."""
    if not len(box):
        return pd.DataFrame()
    g = box.merge(credit, on=["gid", "pid"], how="left") if len(credit) else box.copy()
    for c in ("db_n", "db_epa", "ru_n", "ru_epa", "tg_n", "tg_epa", "db_succ", "ru_succ", "tg_succ"):
        if c not in g:
            g[c] = 0.0
        g[c] = g[c].fillna(0.0)
    g["defp"] = def_points(g)
    g["stp"] = st_points(g)
    team_main = g.groupby(["pid", "team"]).size().reset_index(name="n").sort_values("n").drop_duplicates("pid", keep="last")
    agg = g.groupby("pid").agg(gp=("gid", "nunique"), **{c: (c, "sum") for c in STAT_COLS + [
        "db_n", "db_epa", "ru_n", "ru_epa", "tg_n", "tg_epa", "db_succ", "ru_succ", "tg_succ", "defp", "stp"]}).reset_index()
    agg = agg.merge(team_main[["pid", "team"]], on="pid", how="left")
    agg["tgt"] = agg["tg_n"]
    pos = []
    for r in agg.to_dict("records"):
        p = pos_map.get(r["pid"])
        if p in (None, "ATH") or (p == "OL" and (r["rush_car"] + r["rec"] + r["tkl"]) > 3):
            p = infer_pos(pd.Series(r))
        pos.append(p)
    agg["pos"] = pos
    # skill: EPA by role, replacement from non-starters
    agg["skill_epa"] = np.select(
        [agg["pos"] == "QB", agg["pos"] == "RB", agg["pos"].isin(["WR", "TE"])],
        [agg["db_epa"] + agg["ru_epa"], agg["ru_epa"] + agg["tg_epa"], agg["tg_epa"] + agg["ru_epa"]], 0.0)
    agg["skill_n"] = np.select(
        [agg["pos"] == "QB", agg["pos"] == "RB", agg["pos"].isin(["WR", "TE"])],
        [agg["db_n"] + agg["ru_n"], agg["ru_n"] + agg["tg_n"], agg["tg_n"] + agg["ru_n"]], 0.0)
    agg["value"] = 0.0
    repl = {}
    for p in POS_ORDER:
        m = agg["pos"] == p
        if not m.any():
            continue
        x = agg[m].copy()
        vol = x["skill_n"] if p in SKILL else (x["gp"] * 1.0 if p in DEF else x["gp"])
        x["_vol"] = vol
        x["_rk"] = x.groupby("team")["_vol"].rank(ascending=False, method="first")
        bench = x["_rk"] > STARTERS[p]
        if p in SKILL:
            nb = x.loc[bench, "skill_n"].sum()
            rate = float(x.loc[bench, "skill_epa"].sum() / nb) if nb > 50 else -0.10
            repl[p] = round(rate, 4)
            agg.loc[m, "value"] = x["skill_epa"] - rate * x["skill_n"]
        elif p in DEF:
            gb = x.loc[bench, "gp"].sum()
            rate = float(x.loc[bench, "defp"].sum() / gb) if gb > 20 else 1.0
            repl[p] = round(rate, 3)
            agg.loc[m, "value"] = x["defp"] - rate * x["gp"]
        else:
            repl[p] = 0.0
            agg.loc[m, "value"] = x["stp"]
    # returners at other positions keep their return value on top
    other = ~agg["pos"].isin(["K", "P"])
    ret = 0.03 * (agg["kr_yds"] - 21 * agg["kr"]) + 0.05 * (agg["pr_yds"] - 8 * agg["pr"]) + 3 * (agg["kr_td"] + agg["pr_td"])
    agg.loc[other, "value"] = agg.loc[other, "value"] + ret[other]
    agg["value_pg"] = agg["value"] / agg["gp"].clip(lower=1)
    agg["epa"] = agg["db_epa"] + agg["ru_epa"] + agg["tg_epa"]
    agg["epa_play"] = np.where(agg["skill_n"] > 0, agg["skill_epa"] / agg["skill_n"].clip(lower=1), np.nan)
    agg["pctl"] = 0.0
    for p in POS_ORDER:
        m = agg["pos"] == p
        if m.any():
            agg.loc[m, "pctl"] = agg.loc[m, "value"].rank(pct=True) * 100
    agg["why"] = [why(r) for r in agg.to_dict("records")]
    agg["season"] = int(season)
    agg.attrs["replacement"] = repl
    return agg


def why(r: dict) -> str:
    p = r.get("pos")
    if p == "QB":
        return (f"{int(r['pass_cmp'])}/{int(r['pass_att'])}, {int(r['pass_yds'])} yds, {int(r['pass_td'])} TD, {int(r['pass_int'])} INT; "
                f"{r['db_epa']:+.1f} EPA on {int(r['db_n'])} dropbacks, {r['ru_epa']:+.1f} rushing")
    if p == "RB":
        return f"{int(r['rush_car'])} car, {int(r['rush_yds'])} yds, {int(r['rush_td'])} TD; {r['ru_epa']:+.1f} rush EPA, {r['tg_epa']:+.1f} receiving"
    if p in ("WR", "TE"):
        return f"{int(r['rec'])} rec on {int(r['tg_n'])} targets, {int(r['rec_yds'])} yds, {int(r['rec_td'])} TD; {r['tg_epa']:+.1f} EPA on targets"
    if p in DEF:
        return (f"{int(r['tkl'])} tkl, {r['tfl']:.1f} TFL, {r['sacks']:.1f} sacks, {int(r['pd'])} PD, {int(r['def_int'])} INT "
                f"({r['defp']:.1f} box points)")
    if p == "K":
        return f"FG {int(r['fgm'])}/{int(r['fga'])}, XP {int(r['xpm'])}/{int(r['xpa'])}"
    if p == "P":
        avg = r["punt_yds"] / max(r["punts"], 1)
        return f"{int(r['punts'])} punts, {avg:.1f} avg, {int(r['punt_in20'])} inside 20"
    return ""


# ── team units ──────────────────────────────────────────────────────────────

UNITS = ("QB", "RB", "WR/TE", "OL", "DL/edge", "LB", "DB", "ST")


def team_units(val: pd.DataFrame, tgs: pd.DataFrame | None, fbs: list[str]) -> dict[str, list[dict]]:
    """{team: [{"unit","grade","pctl","value","evidence"}]} graded against the FBS distribution."""
    if not len(val):
        return {}
    v = val[val["team"].isin(fbs)]
    def unit_sum(pos_list, top):
        x = v[v["pos"].isin(pos_list)].sort_values("value", ascending=False)
        return x.groupby("team").head(top).groupby("team")["value"].sum()
    gp = v.groupby("team")["gp"].max().clip(lower=1)
    units = {"QB": unit_sum(["QB"], 1), "RB": unit_sum(["RB"], 2), "WR/TE": unit_sum(["WR", "TE"], 4),
             "DL/edge": unit_sum(["DL"], 4), "LB": unit_sum(["LB"], 3), "DB": unit_sum(["DB"], 4),
             "ST": unit_sum(["K", "P"], 2)}
    units = {k: (s / gp).reindex(fbs).fillna(s.min() / 12 if len(s) else 0.0) for k, s in units.items()}
    ev = {}
    if tgs is not None and len(tgs):
        t = tgs[tgs["team"].isin(fbs)]
        rush = t.groupby("team").apply(lambda x: np.average(x["rush_epa"], weights=x["n_rush"].clip(lower=1)), include_groups=False)
        units["OL"] = rush.reindex(fbs).fillna(rush.median() if len(rush) else 0.0)
        ev["OL"] = {tm: f"rush EPA/play {rush.get(tm, float('nan')):+.3f} (offensive line proxy)" for tm in fbs}
    out: dict[str, list[dict]] = {t: [] for t in fbs}
    for u in UNITS:
        if u not in units:
            continue
        s = units[u]
        pct = s.rank(pct=True) * 100
        for t in fbs:
            pc = float(pct.get(t, 50.0))
            out[t].append({"unit": u, "grade": grade(pc), "pctl": round(pc, 1), "value": round(float(s.get(t, 0.0)), 3),
                           "evidence": (ev.get(u) or {}).get(t) or f"{u} value {float(s.get(t, 0.0)):+.2f} pts/game above replacement"})
    return out


def grade(pctl: float) -> str:
    return "A" if pctl >= 80 else "B" if pctl >= 60 else "C" if pctl >= 40 else "D" if pctl >= 20 else "F"


UNIT_POS = {"QB": ["QB"], "RB": ["RB"], "WR/TE": ["WR", "TE"], "DL/edge": ["DL"], "LB": ["LB"], "DB": ["DB"], "ST": ["K", "P"],
            "OL": []}


def suggestions(team: str, needs: list[dict], val: pd.DataFrame, n: int = 5) -> list[dict]:
    """Portal-style candidates for each need: the highest per-game value at the unit's positions on other teams,
    gain = their value per game minus this team's best at the position (model suggestions only)."""
    out = []
    for nd in needs:
        pos = UNIT_POS.get(nd["unit"]) or []
        if not pos:
            out.append({"need": nd["unit"], "candidates": [], "note": "no individual line data; unit graded from team rushing"})
            continue
        q = val[val["pos"].isin(pos) & (val["gp"] >= 3)]
        own = q[q["team"] == team]["value_pg"].max() if (q["team"] == team).any() else 0.0
        c = q[q["team"] != team].sort_values("value_pg", ascending=False).head(n)
        out.append({"need": nd["unit"], "candidates": [
            {"id": r["pid"], "name": r.get("name"), "team": r["team"], "pos": r["pos"], "class": r.get("class"),
             "value": round(float(r["value"]), 2), "gain": round(float(r["value_pg"] - (own if np.isfinite(own) else 0.0)), 2)}
            for r in c.to_dict("records")]})
    return out


# ── inferred transfers ──────────────────────────────────────────────────────

def moves(prev_val: pd.DataFrame, cur_val: pd.DataFrame, cur_store: dict) -> list[dict]:
    """Players whose main team changed from last season (box) to this season (box, else roster). Inferred."""
    if prev_val is None or not len(prev_val):
        return []
    prev = prev_val.set_index("pid")
    cur = cur_val.set_index("pid") if cur_val is not None and len(cur_val) else pd.DataFrame()
    roster_team: dict[str, str] = {}
    for tid, pids in (cur_store.get("rosters") or {}).items():
        for p in pids or []:
            roster_team[str(p)] = str(tid)
    for pid, p in (cur_store.get("players") or {}).items():
        if pid not in roster_team and p.get("teams"):
            roster_team[pid] = str(p["teams"][-1])
    out = []
    for pid, r in prev.iterrows():
        new = cur.loc[pid, "team"] if pid in cur.index else roster_team.get(pid)
        if not new or str(new) == str(r["team"]):
            continue
        va = float(cur.loc[pid, "value"]) if pid in cur.index else None
        out.append({"player": pid, "pos": r["pos"], "from": str(r["team"]), "to": str(new),
                    "value_before": round(float(r["value"]), 2), "value_after": None if va is None else round(va, 2),
                    "gp_after": int(cur.loc[pid, "gp"]) if pid in cur.index else 0})
    return out


# ── validation ──────────────────────────────────────────────────────────────

def validate(vals: dict[int, pd.DataFrame], attr: dict[int, pd.DataFrame | None], team_off: dict[int, dict] | None = None) -> dict:
    """How far the value numbers can be trusted:
    - attribution: share of pass snaps with a matched passer and target (sacks and throwaways have no target) and
      of rush snaps with a matched ball carrier;
    - stability: correlation of a player's value per credited play (skill) or per game (defence) from one season to
      the next, same position, enough volume both seasons (QB 150 plays, RB/WR/TE 60, defence 8 games);
    - team check: correlation of the summed skill value of a team's players with its opponent-adjusted offensive
      EPA rating (`team_off` {season: {team: epa_off}})."""
    out: dict = {"attribution": [], "stability": {}, "team_check": []}
    for s, a in sorted(attr.items()):
        if a is None or not len(a):
            continue
        ps, ru = a[a["kind"] == "pass"], a[a["kind"] == "rush"]
        out["attribution"].append({"season": int(s), "pass_snaps": int(len(ps)), "rush_snaps": int(len(ru)),
                                   "passer": round(float(ps["passer_id"].notna().mean()), 3) if len(ps) else None,
                                   "target": round(float(ps["target_id"].notna().mean()), 3) if len(ps) else None,
                                   "rusher": round(float(ru["rusher_id"].notna().mean()), 3) if len(ru) else None})
    ss = sorted(vals)
    mins = {"QB": 150, "RB": 60, "WR": 60, "TE": 60}
    for pos in ("QB", "RB", "WR", "TE", "DL", "LB", "DB"):
        xs, ys = [], []
        for s in ss:
            if s + 1 not in vals:
                continue
            a, b = vals[s], vals[s + 1]
            if not len(a) or not len(b):
                continue
            a = a[a["pos"] == pos]
            b = b[b["pos"] == pos]
            if pos in mins:
                a = a[a["skill_n"] >= mins[pos]]
                b = b[b["skill_n"] >= mins[pos]]
                ka, kb = a.set_index("pid")["value"] / a.set_index("pid")["skill_n"], b.set_index("pid")["value"] / b.set_index("pid")["skill_n"]
            else:
                a = a[a["gp"] >= 8]
                b = b[b["gp"] >= 8]
                ka, kb = a.set_index("pid")["value_pg"], b.set_index("pid")["value_pg"]
            common = ka.index.intersection(kb.index)
            xs.extend(ka.loc[common].tolist())
            ys.extend(kb.loc[common].tolist())
        if len(xs) >= 20:
            out["stability"][pos] = {"n": len(xs), "r": round(float(np.corrcoef(xs, ys)[0, 1]), 3),
                                     "metric": "value per credited play" if pos in mins else "value per game"}
    for s in ss:
        v, to = vals[s], (team_off or {}).get(s) or {}
        if not len(v) or not to:
            continue
        sk = v[v["pos"].isin(SKILL)].groupby("team")["value"].sum() / v.groupby("team")["gp"].max().clip(lower=1)
        common = [t for t in sk.index if to.get(t) is not None]
        if len(common) >= 30:
            out["team_check"].append({"season": int(s), "n": len(common),
                                      "r": round(float(np.corrcoef([sk[t] for t in common], [to[t] for t in common])[0, 1]), 3)})
    return out
