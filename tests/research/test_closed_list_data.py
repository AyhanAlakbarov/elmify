"""The committed list files, parsed and checked without a database write.

These are data tests: they pin that the files load, that the owner-named
intergovernmental set is present, and that the global list is not sized to one
corridor (spec 19, build item 7).
"""

from datetime import date

import pytest

from apps.funding.regions import REGIONS
from apps.research.closed_lists import LISTS_DIR, REGISTRY, read_list_file, read_registry
from apps.research.models import ClosedList

pytestmark = pytest.mark.django_db

#: The owner's named set (brief and spec 16 item 7), matched on the body name
#: the file carries, case-folded. A name, not a domain: a body that moves its
#: site must not fail this test, and a body missing from the file must.
_NAMED = (
    "world bank", "islamic development bank", "asian development bank",
    "african development bank", "inter-american development bank", "commonwealth",
    "mastercard foundation", "visegrad", "nordic council", "eea grants", "opec fund",
    "unesco", "aga khan",
)


def _spec(slug: str) -> ClosedList:
    row = next(spec for spec in read_registry() if spec["slug"] == slug)
    return ClosedList(**row)


def test_every_registry_row_parses_and_every_rows_file_has_a_registry_row() -> None:
    slugs = {str(spec["slug"]) for spec in read_registry(REGISTRY)}
    files = {path.stem for path in LISTS_DIR.glob("*.csv")}
    assert files <= slugs, f"rows files with no registry row: {files - slugs}"
    for slug in files:
        assert read_list_file(_spec(slug))


def test_the_intergovernmental_list_carries_the_owner_named_set() -> None:
    names = " | ".join(row.name.casefold() for row in read_list_file(_spec("igo_regional_global")))
    missing = [body for body in _NAMED if body not in names]
    assert not missing, f"named bodies absent from the list: {missing}"


def test_the_intergovernmental_list_is_not_sized_to_one_corridor() -> None:
    """At least one scheme funds students from neither launch country -- the
    list serves a Nigerian applicant as well as an Azerbaijani one."""
    def reaches(cells: tuple[str, ...], country: str) -> bool:
        return "ANY" in cells or country in cells or any(
            country in REGIONS[cell].countries for cell in cells if cell in REGIONS
        )

    rows = read_list_file(_spec("igo_regional_global"))
    assert any(
        not reaches(row.home_cells, "AZ") and not reaches(row.home_cells, "TR")
        for row in rows if not row.rejected_reason
    )


def test_no_list_row_is_verified_in_the_future() -> None:
    for path in LISTS_DIR.glob("*.csv"):
        for row in read_list_file(_spec(path.stem)):
            assert row.verified_on <= date.today(), (path.name, row.external_key)
