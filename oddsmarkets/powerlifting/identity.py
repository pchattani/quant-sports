"""Lifter identity: one OpenPowerlifting Name can hold several people.

OpenPowerlifting gives two same-name lifters a "#N" suffix ("Wei Wang #2") once someone reports them; until then every
lifter of that name shares one Name. "Matthew Taylor" in the archive is an Australian in 1993, an American master, a
Canadian at 100 kg, an Arizona teenager at 150 kg and a British master at 80 kg on one record, and keying lifters on the
bare Name merged them into one page, one rating and one ranking row.

The rule (pids):
  - A Name with a "#N" suffix is OpenPowerlifting's own decision: one lifter, id canon.pid(Name).
  - Any other Name keeps one id unless its rows hold enough evidence that two of them cannot be one person. Evidence
    between two rows, in points; two rows conflict at 1 point:
      * two sexes: 1;
      * birth years apart (from Age, and BirthYearClass): 1 at 6 years or more, 0.5 at 2 to 5 (one year is slack;
        a small gap needs a second signal). The full point needs both birth years confirmed by another meet under
        the name; an unconfirmed one (a single typed-in age, 24 for a 34-year-old) is worth 0.5 at most;
      * an age below 5 or above 95 at the other row's meet, from a confirmed birth year: 1;
      * a bodyweight change: 1 above 20% plus 20% a year between the weigh-ins (no lifter does that), 0.5 above 10%
        plus 10% a year;
      * two nationalities (Country; home nations, dependencies and former states grouped): 0.5, and none when both
        rows carry an Age that agrees (a slip such as Austria for Australia, or a team entry under another flag).
    Against a lifter already formed, a row adds 0.5 when it shares no country (nationality or meet country) with any
    of that lifter's rows, and 0.5 when that lifter's last meet is more than ten years before it. Birth-year and
    nationality points are dropped against a lifter the row twins (same federation, weigh-in within 3% and a year).
    Two different totals at one meet are not evidence: the archive files some meets' Open and Junior competitions
    under one meet.
  - Rows are assigned in date order. A row joins a lifter it does not conflict with (the strongest pair, plus the
    lifter-level points, stays under 1); among those, one it twins, then one that shares its country, then the same
    federation, then the nearest (bodyweight against the lifter's last weigh-in plus a tenth per year since the
    lifter's last meet, to 0.1), then the lifter with more rows. A row that fits none starts a new lifter.
  - The plain id canon.pid(Name) goes to the lifter with the most rows in the archive's last two years (then the most
    rows), so a link to an active lifter keeps working; every other lifter gets
    canon.pid(f"{Name}|{meet_id of its first row}").

Nationality alone never splits a name (international lifters change flags and entries carry slips), and one stray age
never does either. What the rule cannot see stays merged: two same-name lifters with no age, the same country and a
similar bodyweight.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import canon

SLACK_YEARS = 1.0
AGE_GAP_HARD = 6.0
AGE_MIN, AGE_MAX = 5.0, 95.0
BW_HARD = (0.20, 0.20)        # |ln bw ratio| above base + per-year * years apart
BW_SOFT = (0.10, 0.10)
DORMANT_YEARS = 10.0
RECENT_DAYS = 730.0
TWIN_BW, TWIN_DAYS = 0.03, 365.0

# nationalities that are one for this purpose (a lifter listed under either is not a contradiction)
_NAT_GROUP = {
    "England": "UK", "Scotland": "UK", "Wales": "UK", "N.Ireland": "UK", "Isle of Man": "UK", "Gibraltar": "UK",
    "Bermuda": "UK", "Cayman Islands": "UK", "British Virgin Islands": "UK",
    "West Germany": "Germany", "East Germany": "Germany",
    "Puerto Rico": "USA", "US Virgin Islands": "USA", "American Samoa": "USA", "Guam": "USA",
    "Tahiti": "France", "French Polynesia": "France", "New Caledonia": "France", "Wallis and Futuna": "France",
    "Cook Islands": "New Zealand", "Niue": "New Zealand",
    "Faroe Islands": "Denmark", "Aruba": "Netherlands", "Hong Kong": "China",
    "Abkhazia": "Georgia", "Transnistria": "Moldova", "Rhodesia": "Zimbabwe",
}
# former states: compatible with any of their successors, so with anything
_NAT_WILD = {"USSR", "Yugoslavia", "Czechoslovakia", "Serbia and Montenegro", "Netherlands Antilles"}


def nat_group(country) -> str:
    if not isinstance(country, str) or not country or country in _NAT_WILD:
        return ""
    return _NAT_GROUP.get(country, country)


def birth_years(date, age, byc) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(lo, hi, from_age): the birth-year interval each row allows (-inf/inf when unknown), and whether an Age gave it.

    Age n on a date in year Y: born Y-n-1 or Y-n. Age n.5 (OpenPowerlifting: n or n+1): born Y-n-2 .. Y-n.
    BirthYearClass lo-hi (the age reached in year Y): born Y-hi .. Y-lo. Both apply when both are given."""
    y = pd.to_numeric(pd.Series(date).astype(str).str[:4], errors="coerce").to_numpy(float)
    a = pd.to_numeric(pd.Series(age), errors="coerce").to_numpy(float)
    known = np.isfinite(a)
    n = np.floor(np.where(known, a, 0.0))
    half = known & (np.where(known, a, 0.0) - n > 0.25)
    lo = np.where(known, y - n - np.where(half, 2.0, 1.0), -np.inf)
    hi = np.where(known, y - n, np.inf)
    cls = pd.Series(byc).fillna("").astype(str).str.extract(r"^(\d+)-(\d+)$").astype(float)
    clo, chi = y - cls[1].to_numpy(float), y - cls[0].to_numpy(float)
    has = np.isfinite(clo) & np.isfinite(chi)
    lo = np.where(has, np.maximum(lo, clo), lo)
    hi = np.where(has, np.minimum(hi, chi), hi)
    return lo, hi, known


def _frame(entries: pd.DataFrame) -> pd.DataFrame:
    def col(c, default=""):
        return entries[c] if c in entries.columns else pd.Series(default, index=entries.index)
    date = col("date").astype(str)
    lo, hi, from_age = birth_years(date, col("age", np.nan), col("byc"))
    f = pd.DataFrame({
        "name": col("name").astype(str).to_numpy(),
        "sex": col("sex").fillna("").astype(str).to_numpy(),
        "date": date.to_numpy(),
        "meet_id": col("meet_id").astype(str).to_numpy(),
        "nat": [nat_group(x) for x in col("country").to_numpy()],
        "mc": [nat_group(x) for x in col("meet_country").to_numpy()],
        "fed": col("fed").fillna("").astype(str).to_numpy(),
        "bw": pd.to_numeric(col("bw", np.nan), errors="coerce").to_numpy(float),
        "lo": lo, "hi": hi, "ex": from_age,
        "yr": pd.to_numeric(date.str[:4], errors="coerce").to_numpy(float),
    })
    f["t"] = (pd.to_datetime(f["date"], errors="coerce") - pd.Timestamp("1900-01-01")).dt.days.to_numpy(float)
    return f


def _suspects(f: pd.DataFrame) -> set:
    """Names (without a #N suffix) with at least one possible signal: a cheap screen before the row-by-row pass.

    Exact for sex, birth years, nationality and the age bounds; bodyweight and the dormant-and-abroad pair are checked
    between consecutive rows."""
    g = f[~f["name"].str.contains("#", regex=False)]
    by = g.groupby("name")
    out = set()
    out |= set((by["lo"].max() - by["hi"].min() > SLACK_YEARS).loc[lambda s: s].index)
    out |= set((by["sex"].nunique() > 1).loc[lambda s: s].index)
    nat = g[g["nat"] != ""].groupby("name")["nat"].nunique()
    out |= set(nat[nat > 1].index)
    span = by["yr"].max() - by["hi"].min()
    young = by["yr"].min() - by["lo"].max()
    out |= set(span[span > AGE_MAX].index) | set(young[young < AGE_MIN].index)
    s = g.sort_values(["name", "t"])
    nm, bw, t = s["name"].to_numpy(), s["bw"].to_numpy(float), s["t"].to_numpy(float)
    if len(s) > 1:
        same = nm[1:] == nm[:-1]
        dt = np.abs(t[1:] - t[:-1]) / 365.25
        with np.errstate(divide="ignore", invalid="ignore"):
            jump = np.abs(np.log(bw[1:] / bw[:-1])) > BW_SOFT[0] + BW_SOFT[1] * dt
        out |= set(nm[1:][same & jump])
        cc = (s["nat"].where(s["nat"] != "", s["mc"])).to_numpy()
        moved = (cc[1:] != "") & (cc[:-1] != "") & (cc[1:] != cc[:-1])
        out |= set(nm[1:][same & moved & (dt > DORMANT_YEARS)])
    return out


def _pair_points(i: int, c: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Evidence (points) that row i and each earlier row j < i are two people: (hard, soft, twin).

    hard: sex, the age bounds, bodyweight.
    soft: birth years and nationality, which a slip in one entry can produce; dropped against a lifter the row twins.
    twin: the same federation, weigh-ins within 3% and a year of each other."""
    j = slice(0, i)
    lo, hi, ex, ok, yr = c["lo"], c["hi"], c["ex"], c["ok"], c["yr"]
    gap = np.maximum(lo[i] - hi[j], lo[j] - hi[i])
    soft = np.where((gap >= AGE_GAP_HARD) & ok[i] & ok[j], 1.0, np.where(gap > SLACK_YEARS, 0.5, 0.0))
    same_by = ex[i] & ex[j] & (gap <= SLACK_YEARS)
    lo, hi = c["loc"], c["hic"]
    nat = c["nat"]
    soft += np.where((nat[j] != "") & (nat[i] != "") & (nat[j] != nat[i]) & ~same_by, 0.5, 0.0)
    hard = np.where(c["sex"][j] != c["sex"][i], 1.0, 0.0)
    hard += np.where((yr[j] - lo[i] < AGE_MIN) | (yr[j] - hi[i] > AGE_MAX) | (yr[i] - lo[j] < AGE_MIN) | (yr[i] - hi[j] > AGE_MAX), 1.0, 0.0)
    bw, t = c["bw"], c["t"]
    days = np.abs(t[i] - t[j])
    yrs = days / 365.25
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.abs(np.log(bw[i] / bw[j]))            # NaN when a weigh-in is missing: no points
    hard += np.where(r > BW_HARD[0] + BW_HARD[1] * yrs, 1.0, np.where(r > BW_SOFT[0] + BW_SOFT[1] * yrs, 0.5, 0.0))
    twin = (c["fed"][j] == c["fed"][i]) & (r <= TWIN_BW) & (days <= TWIN_DAYS)
    return hard, soft, twin


def _split(g: pd.DataFrame) -> np.ndarray:
    """Lifter labels 0.. for the rows of one Name, in the order given (date order)."""
    n = len(g)
    c = {k: g[k].to_numpy() for k in ("sex", "nat", "mc", "fed")}
    c.update({k: g[k].to_numpy(float) for k in ("lo", "hi", "bw", "t", "yr")})
    c["ex"] = g["ex"].to_numpy(bool)
    # a birth year is confirmed when another meet of the name agrees with it (one typed-in age is not a lifter)
    lo, hi = c["lo"], c["hi"]
    known = np.isfinite(lo) | np.isfinite(hi)
    meet = g["meet_id"].to_numpy()
    agree = (np.maximum(lo[:, None] - hi[None, :], lo[None, :] - hi[:, None]) <= SLACK_YEARS) & (meet[:, None] != meet[None, :])
    c["ok"] = ok = known & (agree & known[None, :]).any(axis=1)
    c["loc"], c["hic"] = np.where(ok, lo, -np.inf), np.where(ok, hi, np.inf)
    nat, mc, fed, bw, t = c["nat"], c["mc"], c["fed"], c["bw"], c["t"]
    lab = np.full(n, -1)
    lifters: list[dict] = []
    for i in range(n):
        hard, soft, twin = _pair_points(i, c)
        mine = {x for x in (nat[i], mc[i]) if x}
        best, key = -1, None
        for k, info in enumerate(lifters):
            m = lab[:i] == k
            tw = bool(twin[m].any())
            worst = float((hard[m] + (0.0 if tw else soft[m])).max())
            shares = bool(mine & info["cc"])
            if mine and info["cc"] and not shares:
                worst += 0.5
            if (t[i] - info["last"]) / 365.25 > DORMANT_YEARS:
                worst += 0.5
            if worst >= 1.0:
                continue
            dbw = abs(np.log(bw[i] / info["bw"])) if np.isfinite(bw[i]) and np.isfinite(info["bw"]) else 0.0
            near = round(dbw + 0.1 * abs(t[i] - info["last"]) / 365.25, 1)
            kk = (tw, shares, fed[i] in info["feds"], -near, info["n"])
            if key is None or kk > key:
                best, key = k, kk
        if best < 0:
            lifters.append({"cc": set(), "feds": set(), "last": t[i], "bw": np.nan, "n": 0})
            best = len(lifters) - 1
        info = lifters[best]
        info["cc"] |= mine
        info["feds"].add(fed[i])
        info["last"] = t[i]
        info["n"] += 1
        if np.isfinite(bw[i]):
            info["bw"] = bw[i]
        lab[i] = best
    return lab


def pids(entries: pd.DataFrame) -> pd.Series:
    """The lifter id of every row (index aligned with `entries`, order kept). Columns used: name, sex, date, meet_id,
    country, meet_country, fed, bw, age, byc (the parsed entries frame; a missing optional column counts as unknown)."""
    f = _frame(entries)
    out = f["name"].map(canon.pid).to_numpy(dtype=object)
    sus = _suspects(f)
    if not sus:
        return pd.Series(out, index=entries.index)
    hit = f["name"].isin(sus).to_numpy()
    sub = f[hit].assign(_i=np.flatnonzero(hit)).sort_values(["name", "date", "meet_id", "_i"], kind="stable")
    names = sub["name"].to_numpy()
    starts = np.flatnonzero(np.r_[True, names[1:] != names[:-1]])
    ends = np.r_[starts[1:], len(sub)]
    recent_from = np.nanmax(f["t"].to_numpy(float)) - RECENT_DAYS
    for a, b in zip(starts, ends):
        g = sub.iloc[a:b]
        lab = _split(g)
        if lab.max() == 0:
            continue
        size = np.bincount(lab)
        recent = np.bincount(lab, weights=(g["t"].to_numpy(float) >= recent_from).astype(float), minlength=len(size))
        first: dict[int, str] = {}
        for k, mid in zip(lab, g["meet_id"].to_numpy()):
            first.setdefault(int(k), mid)
        # the plain id: most rows in the archive's last two years, then most rows, then the earliest lifter
        keep = int(np.lexsort((np.arange(len(size)), -size, -recent))[0])
        nm = names[a]
        used = {canon.pid(nm)}
        ids = {keep: canon.pid(nm)}
        for k in range(len(size)):
            if k == keep:
                continue
            base = f"{nm}|{first[k]}"
            pid, m = canon.pid(base), 2
            while pid in used:
                pid, m = canon.pid(f"{base}|{m}"), m + 1
            used.add(pid)
            ids[k] = pid
        out[g["_i"].to_numpy()] = [ids[int(k)] for k in lab]
    return pd.Series(out, index=entries.index)


def split_report(entries: pd.DataFrame, pid_col: str = "pid") -> dict:
    """How many Names hold more than one lifter under the rule: names split, lifters they became, rows moved off the
    plain id."""
    plain = entries["name"].map(canon.pid)
    per = entries.groupby("name")[pid_col].nunique()
    split = per[per > 1]
    return {"names": int(per.size), "names_split": int(len(split)), "lifters_from_split_names": int(split.sum()),
            "rows_moved": int((entries[pid_col] != plain).sum())}
