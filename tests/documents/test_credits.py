from decimal import Decimal

from apps.documents.credits import to_ects


def test_ects_is_unchanged():
    assert to_ects(Decimal("6"), "ECTS") == Decimal("6.00")


def test_a_us_semester_hour_is_two_ects():
    # A full-time US year is 30 semester hours; a full-time ECTS year is 60.
    assert to_ects(Decimal("3"), "US_SEMESTER_HOUR") == Decimal("6.00")


def test_a_uk_cats_credit_is_half_an_ects():
    # A full-time UK undergraduate year is 120 CATS credits; 60 ECTS / 120 CATS = 0.5.
    assert to_ects(Decimal("15"), "UK_CATS") == Decimal("7.50")
    assert to_ects(Decimal("20"), "UK_CATS") == Decimal("10.00")


def test_a_us_quarter_hour_and_ru_zet_convert_by_statutory_year_load():
    # A full-time US quarter-system year is 45 quarter hours; 60 / 45 = 4/3 ECTS.
    assert to_ects(Decimal("4.5"), "US_QUARTER_HOUR") == Decimal("6.00")
    assert to_ects(Decimal("4"), "US_QUARTER_HOUR") == Decimal("5.33")
    # Russian Federal State Educational Standard (ФГОС) ЗЕТ is 60 per full-time year (1:1 ECTS).
    assert to_ects(Decimal("6"), "RU_ZET") == Decimal("6.00")


def test_a_local_credit_scales_by_the_full_year_load():
    assert to_ects(Decimal("5"), "LOCAL", local_credits_per_year=Decimal("40")) == Decimal("7.50")


def test_a_local_credit_without_a_year_load_is_unknown_not_guessed():
    assert to_ects(Decimal("5"), "LOCAL") is None


def test_an_unknown_unit_is_unknown():
    assert to_ects(Decimal("5"), "UNKNOWN", local_credits_per_year=Decimal("60")) is None
