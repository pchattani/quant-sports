"""
Historical results and bookmaker odds from football-data.co.uk (free CSVs).

Two families of files:

Main leagues  https://www.football-data.co.uk/mmz4281/<season>/<div>.csv
    One file per division and season (season code "2324" = 2023/24). Since 2019/20
    they carry, per match:
      PSH/PSD/PSA        Pinnacle 1X2 at the *pre-closing* snapshot. football-data
                         collects these on Friday afternoon for weekend games and on
                         Tuesday for midweek games; the file does not record the
                         exact time. This is "pinnacle_open" in the edge files, and
                         it is an early-ish line, not the true opening line.
      PSCH/PSCD/PSCA     Pinnacle 1X2 closing.
      MaxH.., AvgH..     market max / average at the snapshot; MaxCH.., AvgCH.. at close
      P>2.5, P<2.5, PC>2.5, PC<2.5, Max>2.5 ...   totals 2.5 (Pinnacle, max), both times
      AHh, PAHH, PAHA, AHCh, PCAHH, PCAHA ...     Asian handicap line and prices
      HS, AS, HST, AST, HC, AC, HF, AF, HY, AY, HR, AR   match statistics (most divisions)
    Before 2019/20 the Pinnacle columns are PSH.. (snapshot) and PSCH.. (close, from
    2012/13), and the over/under and AH columns use the BbMx/BbAv names.

Extra leagues https://www.football-data.co.uk/new/<CODE>.csv
    One file per country with every season (Brazil, Argentina, USA, Mexico, Japan ...),
    with *closing* prices only: PSCH/PSCD/PSCA, MaxC*, AvgC*, BFEC* (Betfair exchange).

Download policy: each file is fetched once and cached under data/football/odds/raw/
(git-ignored). Past seasons are never re-fetched; the current season's files are
re-fetched only when older than `max_age_hours` and only when asked. One request at a
time with a pause between them.
"""
from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE = "https://www.football-data.co.uk"
ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = ROOT / "data" / "football" / "odds" / "raw"
HEADERS = {"User-Agent": "The Quant Footballer research (+https://pchattani.github.io/the-quant-footballer/)"}
PAUSE_S = 1.5
TIMEOUT = 30

# football-data division code -> (our league key, country, tier). The key is the site's
# competition slug where the site follows the league, else a descriptive slug.
MAIN_DIVISIONS: dict[str, tuple[str, str, int]] = {
    "E0": ("premier-league", "ENG", 1),
    "E1": ("championship", "ENG", 2),
    "E2": ("league-one", "ENG", 3),
    "E3": ("league-two", "ENG", 4),
    "EC": ("national-league", "ENG", 5),
    "SC0": ("scottish-premiership", "SCO", 1),
    "SC1": ("scottish-championship", "SCO", 2),
    "D1": ("bundesliga", "GER", 1),
    "D2": ("2-bundesliga", "GER", 2),
    "I1": ("serie-a", "ITA", 1),
    "I2": ("serie-b", "ITA", 2),
    "SP1": ("la-liga", "ESP", 1),
    "SP2": ("segunda", "ESP", 2),
    "F1": ("ligue-1", "FRA", 1),
    "F2": ("ligue-2", "FRA", 2),
    "N1": ("eredivisie", "NED", 1),
    "B1": ("belgian-pro-league", "BEL", 1),
    "P1": ("primeira-liga", "POR", 1),
    "T1": ("super-lig", "TUR", 1),
    "G1": ("super-league-greece", "GRE", 1),
}

# Extra-league file code -> (our league key, country). Files hold every season.
EXTRA_LEAGUES: dict[str, tuple[str, str]] = {
    "BRA": ("brasileirao", "BRA"),
    "ARG": ("liga-argentina", "ARG"),
    "USA": ("mls", "USA"),
    "MEX": ("liga-mx", "MEX"),
    "JPN": ("j1-league", "JPN"),
    "AUT": ("austrian-bundesliga", "AUT"),
    "SWZ": ("swiss-super-league", "SUI"),
    "DNK": ("danish-superliga", "DEN"),
    "NOR": ("eliteserien", "NOR"),
    "SWE": ("allsvenskan", "SWE"),
    "POL": ("ekstraklasa", "POL"),
    "ROU": ("liga-1-romania", "ROU"),
    "IRL": ("league-of-ireland", "IRL"),
    "FIN": ("veikkausliiga", "FIN"),
    "CHN": ("chinese-super-league", "CHN"),
}

SITE_LEAGUES = {"premier-league", "la-liga", "serie-a", "bundesliga", "ligue-1", "eredivisie", "primeira-liga",
                "belgian-pro-league", "brasileirao", "mls", "liga-mx", "liga-argentina"}


def season_codes(first: int = 2012, last: int | None = None) -> list[str]:
    """Season codes '1213' .. for seasons starting in first..last (default: the current one)."""
    now = datetime.now(timezone.utc)
    if last is None:
        last = now.year if now.month >= 7 else now.year - 1
    return [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(first, last + 1)]


def _current_season_code() -> str:
    return season_codes()[-1]


def _fetch(url: str, path: Path, *, refresh: bool, max_age_hours: float) -> Path | None:
    if path.exists() and path.stat().st_size > 0:
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if not refresh or age_h < max_age_hours:
            return path
    path.parent.mkdir(parents=True, exist_ok=True)
    time.sleep(PAUSE_S)
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:  # pragma: no cover - network
        logger.warning("football-data: %s failed: %s", url, exc)
        return path if path.exists() else None
    if r.status_code == 404:
        # Remember the miss so we never ask again for a file that does not exist.
        path.with_suffix(".missing").write_text(datetime.now(timezone.utc).isoformat())
        return None
    if r.status_code != 200 or len(r.content) < 100:
        logger.warning("football-data: %s -> HTTP %s", url, r.status_code)
        return path if path.exists() else None
    path.write_bytes(r.content)
    return path


def download(divisions: list[str] | None = None, seasons: list[str] | None = None, extras: list[str] | None = None,
             *, refresh_current: bool = False, max_age_hours: float = 24.0) -> list[Path]:
    """Fetch (or reuse) the raw CSVs. Returns the cached paths that exist."""
    divisions = list(MAIN_DIVISIONS) if divisions is None else divisions
    seasons = season_codes() if seasons is None else seasons
    extras = list(EXTRA_LEAGUES) if extras is None else extras
    cur = _current_season_code()
    out: list[Path] = []
    for s in seasons:
        for d in divisions:
            p = RAW_DIR / "mmz4281" / s / f"{d}.csv"
            if p.with_suffix(".missing").exists():
                continue
            got = _fetch(f"{BASE}/mmz4281/{s}/{d}.csv", p, refresh=refresh_current and s == cur, max_age_hours=max_age_hours)
            if got:
                out.append(got)
    for code in extras:
        p = RAW_DIR / "new" / f"{code}.csv"
        got = _fetch(f"{BASE}/new/{code}.csv", p, refresh=refresh_current, max_age_hours=max_age_hours)
        if got:
            out.append(got)
    return out


# ── parsing ──────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    # Some old files have trailing commas / ragged rows.
    df = pd.read_csv(io.StringIO(text), on_bad_lines="skip", low_memory=False)
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    return df.dropna(how="all")


def _num(df: pd.DataFrame, *names: str) -> pd.Series:
    """First present column among names, as float (NaN where absent)."""
    for n in names:
        if n in df.columns:
            return pd.to_numeric(df[n], errors="coerce")
    return pd.Series(np.nan, index=df.index, dtype=float)


def _kickoff(df: pd.DataFrame) -> pd.Series:
    d = pd.to_datetime(df["Date"].astype(str).str.strip(), format="mixed", dayfirst=True, errors="coerce")
    if "Time" in df.columns:
        t = df["Time"].astype(str).str.strip()
        ok = t.str.match(r"^\d{1,2}:\d{2}$")
        hm = pd.to_timedelta(t.where(ok, "15:00") + ":00", errors="coerce").fillna(pd.Timedelta(hours=15))
    else:
        hm = pd.Timedelta(hours=15)
    # football-data times are UK local time; convert to UTC.
    local = (d + hm).dt.tz_localize("Europe/London", ambiguous="NaT", nonexistent="shift_forward")
    return local.dt.tz_convert("UTC")


STANDARD_COLS = [
    "league", "div", "country", "tier", "season", "start_time", "home", "away", "hg", "ag",
    "hs", "as_", "hst", "ast", "hc", "ac", "hr", "ar",
    "ps_h", "ps_d", "ps_a", "psc_h", "psc_d", "psc_a",
    "max_h", "max_d", "max_a", "maxc_h", "maxc_d", "maxc_a",
    "avg_h", "avg_d", "avg_a", "avgc_h", "avgc_d", "avgc_a",
    "bfec_h", "bfec_d", "bfec_a",
    "pin_o25", "pin_u25", "pc_o25", "pc_u25", "max_o25", "max_u25", "maxc_o25", "maxc_u25",
    "avgc_o25", "avgc_u25", "bfec_o25", "bfec_u25",
    "ah_line", "pah_h", "pah_a", "ahc_line", "pcah_h", "pcah_a", "maxah_h", "maxah_a", "maxcah_h", "maxcah_a",
]


def parse_main(path: Path, div: str, season: str) -> pd.DataFrame:
    df = _read_csv(path)
    if "HomeTeam" not in df.columns and "Home" in df.columns:
        df = df.rename(columns={"Home": "HomeTeam", "Away": "AwayTeam", "HG": "FTHG", "AG": "FTAG"})
    if "HomeTeam" not in df.columns:
        return pd.DataFrame(columns=STANDARD_COLS)
    league, country, tier = MAIN_DIVISIONS[div]
    out = pd.DataFrame({
        "league": league, "div": div, "country": country, "tier": tier,
        "season": f"20{season[:2]}-{season[2:]}",
        "start_time": _kickoff(df),
        "home": df["HomeTeam"].astype(str).str.strip(), "away": df["AwayTeam"].astype(str).str.strip(),
        "hg": _num(df, "FTHG"), "ag": _num(df, "FTAG"),
        "hs": _num(df, "HS"), "as_": _num(df, "AS"), "hst": _num(df, "HST"), "ast": _num(df, "AST"),
        "hc": _num(df, "HC"), "ac": _num(df, "AC"), "hr": _num(df, "HR"), "ar": _num(df, "AR"),
        "ps_h": _num(df, "PSH", "PH"), "ps_d": _num(df, "PSD", "PD"), "ps_a": _num(df, "PSA", "PA"),
        "psc_h": _num(df, "PSCH"), "psc_d": _num(df, "PSCD"), "psc_a": _num(df, "PSCA"),
        "max_h": _num(df, "MaxH", "BbMxH"), "max_d": _num(df, "MaxD", "BbMxD"), "max_a": _num(df, "MaxA", "BbMxA"),
        "maxc_h": _num(df, "MaxCH"), "maxc_d": _num(df, "MaxCD"), "maxc_a": _num(df, "MaxCA"),
        "avg_h": _num(df, "AvgH", "BbAvH"), "avg_d": _num(df, "AvgD", "BbAvD"), "avg_a": _num(df, "AvgA", "BbAvA"),
        "avgc_h": _num(df, "AvgCH"), "avgc_d": _num(df, "AvgCD"), "avgc_a": _num(df, "AvgCA"),
        "bfec_h": _num(df, "BFECH"), "bfec_d": _num(df, "BFECD"), "bfec_a": _num(df, "BFECA"),
        "pin_o25": _num(df, "P>2.5"), "pin_u25": _num(df, "P<2.5"),
        "pc_o25": _num(df, "PC>2.5"), "pc_u25": _num(df, "PC<2.5"),
        "max_o25": _num(df, "Max>2.5", "BbMx>2.5"), "max_u25": _num(df, "Max<2.5", "BbMx<2.5"),
        "maxc_o25": _num(df, "MaxC>2.5"), "maxc_u25": _num(df, "MaxC<2.5"),
        "avgc_o25": _num(df, "AvgC>2.5"), "avgc_u25": _num(df, "AvgC<2.5"),
        "bfec_o25": _num(df, "BFEC>2.5"), "bfec_u25": _num(df, "BFEC<2.5"),
        "ah_line": _num(df, "AHh", "BbAHh"), "pah_h": _num(df, "PAHH"), "pah_a": _num(df, "PAHA"),
        "ahc_line": _num(df, "AHCh"), "pcah_h": _num(df, "PCAHH"), "pcah_a": _num(df, "PCAHA"),
        "maxah_h": _num(df, "MaxAHH", "BbMxAHH"), "maxah_a": _num(df, "MaxAHA", "BbMxAHA"),
        "maxcah_h": _num(df, "MaxCAHH"), "maxcah_a": _num(df, "MaxCAHA"),
    })
    return out.dropna(subset=["start_time"]).reset_index(drop=True)


def parse_extra(path: Path, code: str) -> pd.DataFrame:
    df = _read_csv(path)
    league, country = EXTRA_LEAGUES[code]
    # The "League" column distinguishes e.g. MLS from other US competitions; keep the main one.
    if "League" in df.columns:
        main = df["League"].value_counts().idxmax()
        df = df[df["League"] == main]
    seasons = df["Season"].astype(str).str.strip()
    out = pd.DataFrame({
        "league": league, "div": code, "country": country, "tier": 1,
        "season": seasons.str.replace("/", "-", regex=False),
        "start_time": _kickoff(df),
        "home": df["Home"].astype(str).str.strip(), "away": df["Away"].astype(str).str.strip(),
        "hg": _num(df, "HG"), "ag": _num(df, "AG"),
        "psc_h": _num(df, "PSCH", "PH"), "psc_d": _num(df, "PSCD", "PD"), "psc_a": _num(df, "PSCA", "PA"),
        "maxc_h": _num(df, "MaxCH", "MaxH"), "maxc_d": _num(df, "MaxCD", "MaxD"), "maxc_a": _num(df, "MaxCA", "MaxA"),
        "avgc_h": _num(df, "AvgCH", "AvgH"), "avgc_d": _num(df, "AvgCD", "AvgD"), "avgc_a": _num(df, "AvgCA", "AvgA"),
        "bfec_h": _num(df, "BFECH"), "bfec_d": _num(df, "BFECD"), "bfec_a": _num(df, "BFECA"),
    })
    for c in STANDARD_COLS:
        if c not in out.columns:
            out[c] = np.nan
    return out[STANDARD_COLS].dropna(subset=["start_time"]).reset_index(drop=True)


def load_all(*, download_missing: bool = False) -> pd.DataFrame:
    """Every cached match as one frame (STANDARD_COLS), sorted by kickoff."""
    if download_missing:
        download()
    frames = []
    for p in sorted((RAW_DIR / "mmz4281").glob("*/*.csv")):
        div, season = p.stem, p.parent.name
        if div in MAIN_DIVISIONS:
            try:
                frames.append(parse_main(p, div, season))
            except Exception as exc:  # a malformed old file must not sink the rest
                logger.warning("football-data: could not parse %s: %s", p, exc)
    for p in sorted((RAW_DIR / "new").glob("*.csv")):
        if p.stem in EXTRA_LEAGUES:
            frames.append(parse_extra(p, p.stem))
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame(columns=STANDARD_COLS)
    df = pd.concat(frames, ignore_index=True)[STANDARD_COLS]
    df = df.sort_values(["start_time", "league", "home"]).reset_index(drop=True)
    return df


@dataclass(frozen=True)
class Devig:
    """Proportional (multiplicative) and power de-vigging of a set of decimal prices."""

    @staticmethod
    def proportional(prices: np.ndarray) -> np.ndarray:
        inv = 1.0 / np.asarray(prices, dtype=float)
        return inv / inv.sum(axis=-1, keepdims=True)

    @staticmethod
    def power(prices: np.ndarray, iters: int = 40) -> np.ndarray:
        """Find k with sum (1/p)^k = 1 (removes more margin from longshots)."""
        inv = 1.0 / np.asarray(prices, dtype=float)
        lo = np.full(inv.shape[:-1] + (1,), 1.0)
        hi = np.full_like(lo, 3.0)
        for _ in range(iters):
            mid = 0.5 * (lo + hi)
            s = (inv ** mid).sum(axis=-1, keepdims=True)
            lo = np.where(s > 1, mid, lo)
            hi = np.where(s > 1, hi, mid)
        q = inv ** (0.5 * (lo + hi))
        return q / q.sum(axis=-1, keepdims=True)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    paths = download()
    print(f"{len(paths)} files cached under {RAW_DIR}")


# ── mapping to the site's Sofascore teams and events ─────────────────────────

def sofascore_matches(slug: str, site_data: Path | None = None) -> pd.DataFrame:
    """Every finished Sofascore match of a competition we hold: the live store (current and
    previous season) and the past-results store. Columns: sofa_id, date, home, away, home_id,
    away_id, hs, as."""
    import json
    site_data = site_data or ROOT / "docs" / "site" / "data"
    rows = []
    paths = [site_data / slug / "store.json", site_data / "past" / "store.json"]
    if slug == "liga-argentina" and not paths[0].exists():
        paths.append(ROOT / "docs" / "liga" / "data" / "liga_store.json")     # before the store moved (round 6)
    for p in paths:
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if p.parent.name == "past":
            ms = {}
            for sid, s in (d.get("seasons", {}).get(slug) or {}).items():
                ms.update(s.get("matches") or {})
        else:
            ms = d.get("matches") or {}
        for mid, m in ms.items():
            if m.get("hs") is None or m.get("as") is None or not m.get("date"):
                continue
            rows.append({"sofa_id": int(mid), "date": m["date"], "home": m.get("home"), "away": m.get("away"),
                         "home_id": m.get("home_id"), "away_id": m.get("away_id"), "hs": m["hs"], "as": m["as"]})
    df = pd.DataFrame(rows).drop_duplicates("sofa_id") if rows else pd.DataFrame(
        columns=["sofa_id", "date", "home", "away", "home_id", "away_id", "hs", "as"])
    if len(df):
        df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


def map_to_sofascore(fd_league: pd.DataFrame, slug: str) -> tuple[dict[str, tuple[str, int]], pd.Series]:
    """
    Map football-data team names to Sofascore (name, id) by matching fixtures: same day
    (within 1 day of kickoff) and the same score. Each football-data team takes the
    Sofascore team it is most often paired with (at least 3 agreeing fixtures and half of
    its candidate pairings). Returns the team map and, per football-data row, the
    Sofascore event id where both teams map and the fixture is found.
    """
    S = sofascore_matches(slug)
    ev = pd.Series(pd.NA, index=fd_league.index, dtype="Int64")
    if not len(S):
        return {}, ev
    S = S.rename(columns={"as": "as_"}).assign(day=S["date"].dt.floor("D"))
    by_day: dict = {}
    for r in S.itertuples(index=False):
        by_day.setdefault(r.day, []).append(r)
    votes: dict[str, dict[tuple[str, int], int]] = {}
    for r in fd_league.itertuples():
        day = r.start_time.floor("D")
        for dd in (day, day - pd.Timedelta(days=1), day + pd.Timedelta(days=1)):
            for s in by_day.get(dd, []):
                if s.hs == r.hg and s.as_ == r.ag:
                    votes.setdefault(r.home, {}).setdefault((s.home, s.home_id), 0)
                    votes[r.home][(s.home, s.home_id)] += 1
                    votes.setdefault(r.away, {}).setdefault((s.away, s.away_id), 0)
                    votes[r.away][(s.away, s.away_id)] += 1
    team_map = {}
    for t, v in votes.items():
        (best, cnt) = max(v.items(), key=lambda kv: kv[1])
        if cnt >= 3 and cnt >= 0.5 * sum(v.values()):
            team_map[t] = (best[0], int(best[1]))
    # resolve the event ids
    key = {(int(s.home_id), int(s.away_id), s.day): s.sofa_id for s in S.itertuples() if pd.notna(s.home_id) and pd.notna(s.away_id)}
    for i, r in zip(fd_league.index, fd_league.itertuples()):
        h, a = team_map.get(r.home), team_map.get(r.away)
        if not h or not a:
            continue
        day = r.start_time.floor("D")
        for dd in (day, day - pd.Timedelta(days=1), day + pd.Timedelta(days=1)):
            sid = key.get((h[1], a[1], dd))
            if sid is not None:
                ev.at[i] = sid
                break
    return team_map, ev
