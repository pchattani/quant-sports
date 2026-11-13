"""Lifter identity (oddsmarkets/powerlifting/identity.py): a bare OpenPowerlifting Name that holds several people is
split on hard evidence; a "#N" Name, a typed-in age and a change of flag are not."""
import zipfile
from pathlib import Path

import pandas as pd

from oddsmarkets.powerlifting import canon, identity
from oddsmarkets.powerlifting.sources import opl


def _rows(name, rows):
    """rows: (date, country, meet_country, fed, bw, age) -> an entries frame like opl.parse_zip's."""
    out = []
    for k, (date, cc, mc, fed, bw, age) in enumerate(rows):
        out.append({"name": name, "sex": "M", "date": date, "meet_id": f"m{date}{fed}{k}", "country": cc,
                    "meet_country": mc, "fed": fed, "bw": bw, "age": age, "byc": "", "event": "SBD",
                    "equipment": "Raw", "total": 500.0})
    return pd.DataFrame(out)


# the shape of "Matthew Taylor" in the 31 Oct 2026 dump: four people on one Name
TAYLOR = [
    ("1993-07-03", None, "Australia", "AusPF", 100.0, None),
    ("1993-09-24", "Australia", "Australia", "AusPF", 100.0, None),
    ("2020-09-04", None, "England", "WRPF-UK", 80.8, 36.0),
    ("2021-11-26", "UK", "England", "IPL", 80.4, 36.0),
    ("2023-04-08", "UK", "UK", "BPF", 76.75, 38.0),
    ("2023-11-18", "Canada", "Canada", "CPU", 97.12, None),
    ("2024-02-24", "USA", "USA", "USAPL", 153.6, 17.5),
    ("2024-05-18", "Canada", "Canada", "CPU", 100.52, None),
    ("2025-03-15", "USA", "USA", "USAPL", 154.0, 18.5),
    ("2025-10-19", "Canada", "Canada", "CPU", 100.5, None),
    ("2025-11-01", "USA", "USA", "USAPL", 144.6, 18.5),
    ("2026-10-24", "USA", "USA", "USAPL", 138.4, 19.5),
]


def test_a_name_holding_four_lifters_is_split_into_four():
    e = _rows("Matthew Taylor", TAYLOR)
    p = identity.pids(e)
    who = dict(zip(e["date"], p))
    assert p.nunique() == 4
    teen = {who[d] for d in ("2024-02-24", "2025-03-15", "2025-11-01", "2026-10-24")}
    canada = {who[d] for d in ("2023-11-18", "2024-05-18", "2025-10-19")}
    uk = {who[d] for d in ("2020-09-04", "2021-11-26", "2023-04-08")}
    aus = {who[d] for d in ("1993-07-03", "1993-09-24")}
    assert len(teen) == len(canada) == len(uk) == len(aus) == 1
    assert len(teen | canada | uk | aus) == 4
    # the plain id stays with the lifter most active in the last two years (the Arizona teenager: four meets)
    assert teen == {canon.pid("Matthew Taylor")}
    assert identity.split_report(e.assign(pid=p.to_numpy())) == {
        "names": 1, "names_split": 1, "lifters_from_split_names": 4, "rows_moved": 8}


def test_index_and_order_are_kept():
    e = _rows("Matthew Taylor", TAYLOR).sample(frac=1.0, random_state=3)
    e.index = e.index + 100
    p = identity.pids(e)
    assert list(p.index) == list(e.index)
    ref = identity.pids(_rows("Matthew Taylor", TAYLOR))
    assert dict(zip(e["date"], p)) == dict(zip(_rows("Matthew Taylor", TAYLOR)["date"], ref))


def test_a_disambiguated_name_is_never_split():
    e = _rows("Wei Wang #2", TAYLOR)
    p = identity.pids(e)
    assert p.nunique() == 1 and p.iloc[0] == canon.pid("Wei Wang #2") != canon.pid("Wei Wang #1")


def test_one_typed_in_age_does_not_make_a_second_lifter():
    rows = [(f"20{y}-0{m}-10", "USA", "USA", "RawIronPL", 65.5 + 0.2 * m, float(y + 11)) for y in (21, 22, 23) for m in (2, 6)]
    rows.append(("2023-08-01", "USA", "USA", "RawIronPL", 66.9, 24.0))       # a 34-year-old typed in as 24
    p = identity.pids(_rows("Christian Kearney", rows))
    assert p.nunique() == 1


def test_a_change_of_flag_alone_does_not_split():
    rows = [("2022-05-22", None, "Bulgaria", "WRPF-Bulgaria", 77.0, 22.0),
            ("2022-07-30", "USA", "USA", "USPA", 77.5, 22.0),              # entered under the meet's flag
            ("2023-12-09", "Bulgaria", "Russia", "WRPF", 77.8, 23.0),
            ("2026-05-14", None, "Serbia", "WRPF-Serbia", 80.4, 26.0)]       # a new country, no flag given
    assert identity.pids(_rows("Viktoriya Ilieva", rows)).nunique() == 1


def test_a_bodyweight_no_one_reaches_in_three_weeks_splits():
    rows = [("2025-10-19", "Canada", "Canada", "CPU", 100.5, None), ("2025-11-08", "Canada", "Canada", "CPU", 73.8, None),
            ("2026-05-30", "Canada", "Canada", "CPU", 98.4, None), ("2026-08-07", "Canada", "Canada", "CPU", 71.5, None)]
    e = _rows("Matthew Taylor", rows)
    p = identity.pids(e)
    assert p.nunique() == 2
    assert p.iloc[0] == p.iloc[2] and p.iloc[1] == p.iloc[3]


def test_parse_zip_keys_lifters_with_the_identity_rule(tmp_path: Path):
    head = ("Name,Sex,Event,Equipment,Age,Division,BodyweightKg,WeightClassKg,Best3SquatKg,Best3BenchKg,Best3DeadliftKg,"
            "TotalKg,Place,Dots,Goodlift,Tested,Country,Federation,ParentFederation,Date,MeetCountry,MeetState,MeetName,"
            "Sanctioned\n")
    lines = []
    for date, cc, mc, fed, bw, age in TAYLOR:
        lines.append(f"Matthew Taylor,M,SBD,Raw,{'' if age is None else age},Open,{bw},,200,120,240,560,1,,,Yes,"
                     f"{cc or ''},{fed},,{date},{mc},,Meet {fed} {date},Yes")
    lines.append("Ada Lovelace,F,SBD,Raw,28,Open,60.0,63,150,90,180,420,1,120.5,90.0,Yes,USA,USAPL,IPF,2024-03-01,USA,TX,Spring Classic,Yes")
    zpath = tmp_path / "opl.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("openpowerlifting.csv", head + "\n".join(lines) + "\n")
    entries, meets = opl.parse_zip(zpath)
    mt = entries[entries["name"] == "Matthew Taylor"]
    assert mt["pid"].nunique() == 4
    assert entries.loc[entries["name"] == "Ada Lovelace", "pid"].tolist() == [canon.pid("Ada Lovelace")]
    assert opl.SCHEMA >= 3          # a store parsed under the old rule is re-parsed by scripts/pl_fetch.py
