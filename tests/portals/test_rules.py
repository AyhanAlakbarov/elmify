import pytest

from apps.portals.rules import format_value


@pytest.mark.parametrize("fmt, expected", [
    ("DD.MM.YYYY", "07.03.2001"), ("MM/DD/YYYY", "03/07/2001"),
    ("YYYY-MM-DD", "2001-03-07"), ("DD/MM/YYYY", "07/03/2001"),
    ("MM/YYYY", "03/2001"), ("MM.YYYY", "03.2001"), ("YYYY-MM", "2001-03"),
])
def test_an_iso_date_is_written_in_the_portals_format(fmt: str, expected: str) -> None:
    assert format_value("2001-03-07", fmt) == expected


@pytest.mark.parametrize("fmt, expected", [
    ("MM/YYYY", "09/2018"),
    ("MM.YYYY", "09.2018"),
    ("YYYY-MM", "2018-09"),
    ("DD.MM.YYYY", "2018-09"),
])
def test_an_iso_month_date_formats_to_month_year_without_inventing_a_day(
    fmt: str, expected: str
) -> None:
    assert format_value("2018-09", fmt) == expected


def test_a_value_that_is_not_an_iso_date_is_never_reformatted() -> None:
    assert format_value("March 2001", "DD.MM.YYYY") == "March 2001"


@pytest.mark.django_db
def test_rules_apply_by_field_class_and_synonyms_replace_the_option_text() -> None:
    from apps.portals.models import PortalForm
    from apps.portals.rules import apply_rules

    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key="rules-1",
        value_formats={"education.end_date": "DD.MM.YYYY"},
        option_synonyms={"personal.nationality": {"Azerbaijan": "Azerbaijan, Republic of"}},
    )
    assert apply_rules(form, "education.2.end_date", "2024-06-30") == "30.06.2024"
    assert apply_rules(form, "personal.nationality", "Azerbaijan") == "Azerbaijan, Republic of"
    assert apply_rules(form, "personal.given_name", "Ləman") == "Ləman"
