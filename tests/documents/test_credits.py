from decimal import Decimal

from apps.documents.credits import to_ects


def test_ects_is_unchanged():
    assert to_ects(Decimal("6"), "ECTS") == Decimal("6.00")


def test_a_us_semester_hour_is_two_ects():
    # A full-time US year is 30 semester hours; a full-time ECTS year is 60.
    assert to_ects(Decimal("3"), "US_SEMESTER_HOUR") == Decimal("6.00")


def test_a_local_credit_scales_by_the_full_year_load():
    assert to_ects(Decimal("5"), "LOCAL", local_credits_per_year=Decimal("40")) == Decimal("7.50")


def test_a_local_credit_without_a_year_load_is_unknown_not_guessed():
    assert to_ects(Decimal("5"), "LOCAL") is None


def test_an_unknown_unit_is_unknown():
    assert to_ects(Decimal("5"), "UNKNOWN", local_credits_per_year=Decimal("60")) is None
