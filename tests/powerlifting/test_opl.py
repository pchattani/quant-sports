import io
import zipfile
from pathlib import Path

from oddsmarkets.powerlifting.sources import opl


CSV = """Name,Sex,Event,Equipment,Age,Division,BodyweightKg,WeightClassKg,Best3SquatKg,Best3BenchKg,Best3DeadliftKg,TotalKg,Place,Dots,Goodlift,Tested,Country,Federation,ParentFederation,Date,MeetCountry,MeetState,MeetName,Sanctioned
Ada Lovelace,F,SBD,Raw,28,Open,60.0,63,150,90,180,420,1,120.5,90.0,Yes,USA,USAPL,IPF,2024-03-01,USA,TX,Spring Classic,Yes
Ada Lovelace,F,SBD,Raw,28,Open,60.5,63,155,92,185,432,1,123.0,91.0,Yes,USA,USAPL,IPF,2024-09-01,USA,TX,Autumn Classic,Yes
Alan Turing,M,SBD,Raw,35,Open,90.0,90,250,160,280,690,2,110.0,80.0,,UK,BP,IPF,2024-03-01,UK,,British Open,Yes
Guest,M,B,Straps,40,Open,100.0,110,,,200,,1,,,Yes,USA,USPA,,2024-03-01,USA,TX,Spring Classic,Yes
"""


def test_parse_zip_keeps_sanctioned_equipped_rows_and_drops_straps(tmp_path: Path):
    zpath = tmp_path / "opl.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("openpowerlifting.csv", CSV)
    entries, meets = opl.parse_zip(zpath)
    assert len(entries) == 3                                  # the Straps bench is dropped
    assert set(entries["name"]) == {"Ada Lovelace", "Alan Turing"}
    assert entries["tested"].tolist() == [True, True, False]
    assert len(meets) == 3
    assert (meets["n_sbd"] >= 1).all()
    ada = entries[entries["name"] == "Ada Lovelace"]
    assert ada["pid"].nunique() == 1
    assert ada["meet_id"].nunique() == 2
