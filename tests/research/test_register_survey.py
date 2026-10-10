"""The register survey (spec 6.2's ladder, 19): one row per corridor country x
family, each stating which rung exists and on what evidence."""

import csv
from datetime import date

import pytest

from apps.research.closed_lists import DATA_DIR, read_registry

SURVEY = DATA_DIR / "register-survey.csv"
_COLUMNS = (
    "country_code", "kind", "rung", "list_url", "maintainer", "purpose_filter",
    "row_carries", "access", "reuse_terms", "reuse_terms_url", "closed_list_slug",
    "surveyed_on", "searched_for", "notes",
)
#: Enforced now. Task 6 Step 6 widens this to every corridor country.
SURVEYED = ("TR", "AZ")
KINDS = (
    "NATIONAL_GOVERNMENT", "SUBNATIONAL_GOVERNMENT", "EMBASSY_BILATERAL",
    "POLITICAL_FOUNDATION", "RELIGIOUS", "PRIVATE_FOUNDATION", "EMPLOYER",
    "PROFESSIONAL_BODY", "BANK_OR_LENDER", "INSTITUTION",
)


def _rows() -> list[dict[str, str]]:
    with SURVEY.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == _COLUMNS
        return list(reader)


def test_every_surveyed_country_has_one_row_per_family() -> None:
    seen = [(row["country_code"], row["kind"]) for row in _rows()]
    assert len(seen) == len(set(seen)), "a (country, kind) surveyed twice"
    missing = [(c, k) for c in SURVEYED for k in KINDS if (c, k) not in set(seen)]
    assert not missing, f"unsurveyed: {missing}"


@pytest.mark.parametrize("row", _rows(), ids=lambda r: f"{r['country_code']}-{r['kind']}")
def test_a_row_states_its_evidence(row: dict[str, str]) -> None:
    assert row["kind"] in KINDS
    assert row["rung"] in {"1", "2", "3", "4"}
    assert row["purpose_filter"] in {"yes", "no", ""}
    assert row["row_carries"] in {"website", "email", "both", "neither", ""}
    assert row["access"] in {"API", "FILE", "WEB_PAGE", "FORM", "NONE"}
    assert row["reuse_terms"] in {"OPEN", "UNREAD", "OWN_COMPILATION", "RESTRICTIVE", "NONE"}
    assert date.fromisoformat(row["surveyed_on"]) <= date.today()
    if row["rung"] == "4":
        assert row["searched_for"].strip(), "rung 4 must say what was searched for"
    else:
        assert row["list_url"].startswith("https://") and row["maintainer"].strip()
        assert row["purpose_filter"] and row["row_carries"]
    assert "@" not in "".join(row.values())


def test_a_named_slug_is_a_registry_row() -> None:
    slugs = {str(spec["slug"]) for spec in read_registry()}
    for row in _rows():
        if row["closed_list_slug"]:
            assert row["closed_list_slug"] in slugs, row
