import csv
import re
from pathlib import Path

from apps.research.disciplines import BUCKETS, UNCLASSIFIABLE

CSV = Path(__file__).resolve().parents[2] / "docs/research/discipline-buckets.csv"

#: ISCED-F 2013's narrow fields, less the three 00x generic programmes.
_ISCED_NARROW = (
    "011 021 022 023 031 032 041 042 051 052 053 054 061 071 072 073 "
    "081 082 083 084 091 092 101 102 103 104"
).split()


def _rows() -> list[dict[str, str]]:
    with CSV.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_the_module_is_the_csv_and_nothing_else() -> None:
    assert tuple(row["slug"] for row in _rows()) == BUCKETS


def test_unclassifiable_is_a_bucket_so_a_thin_reading_is_never_forced_into_a_field() -> None:
    assert UNCLASSIFIABLE == "unclassifiable" and UNCLASSIFIABLE in BUCKETS
    assert BUCKETS[-1] == UNCLASSIFIABLE
    assert len(set(BUCKETS)) == len(BUCKETS)


def test_every_narrow_field_is_a_bucket_once_and_every_slug_is_snake_case() -> None:
    rows = _rows()
    codes = [row["isced_code"] for row in rows if row["slug"] != UNCLASSIFIABLE]
    assert codes == _ISCED_NARROW
    assert all(re.fullmatch(r"[a-z]+(_[a-z]+)*", row["slug"]) for row in rows)
    assert all(row["source_url"] for row in rows)
