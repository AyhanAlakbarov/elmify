import pytest

from apps.research.candidates.spans import find_durations, find_intakes


def test_durations_in_several_languages():
    (d,) = find_durations("for 12 months a year")
    assert (d.count, d.unit, d.months) == (12, "months", 12)
    (d,) = find_durations("Master's: 2 years")
    assert (d.unit, d.months) == ("years", 24)
    (d,) = find_durations("Magistratura: 4 semestr")
    assert (d.count, d.unit, d.months) == (4, "semesters", None)
    (d,) = find_durations("석사과정 : 4학기")
    assert (d.count, d.unit) == (4, "semesters")


def test_the_standard_period_of_study_has_no_number():
    (d,) = find_durations("for the standard period of study")
    assert (d.count, d.unit, d.months) == (None, "programme", None)
    (d,) = find_durations("на весь период обучения")
    assert d.unit == "programme"


def test_a_relative_date_is_not_a_duration():
    assert find_durations("opens approximately 15 months before the start of the grant") == []
    assert find_durations("Namizədlərin siyahısı elan edilir 1 il əvvəl") == []


def test_intakes():
    (i,) = find_intakes("2026/27 academic year")
    assert (i.start_year, i.end_year) == (2026, 2027)
    (i,) = find_intakes("2025-2026-cı tədris ili")
    assert (i.start_year, i.end_year) == (2025, 2026)
    (i,) = find_intakes("Fall 2026 intake")
    assert (i.start_year, i.season) == (2026, "Fall")
    assert find_intakes("Founded in 1998") == []


def test_a_decimal_count_is_never_read_as_its_fraction():
    for line in ("1.5 years", "1,5 years", "0.5 years", "2.5 years"):
        assert find_durations(line) == []
    (d,) = find_durations("2 years")
    assert d.months == 24


def test_turkic_suffixed_units_and_hyphenated_forms():
    for line in ("2 illik magistratura", "2 yıllık", "2 ildə", "2-year master"):
        (d,) = find_durations(line)
        assert (d.unit, d.months) == ("years", 24), line
    (d,) = find_durations("24 aylıq")
    assert (d.unit, d.months) == ("months", 24)
    (d,) = find_durations("12-month programme")
    assert (d.unit, d.months) == ("months", 12)
    for line in ("6 ay əvvəl", "1 il əvvəl", "ilk 3 aylar", "2 ilk"):
        assert find_durations(line) == [], line


def test_spring_and_winter_seasons():
    for line in ("весна 2027", "Kış 2027", "осень 2027"):
        (i,) = find_intakes(line)
        assert i.start_year == 2027, line


@pytest.mark.parametrize("line", ["2-3 years", "2–3 years", "1-2 years", "12-15 months"])
def test_a_count_range_is_no_duration(line):
    assert find_durations(line) == []


def test_single_counts_still_read():
    assert [d.months for d in find_durations("2 years")] == [24]
    assert [d.months for d in find_durations("2-year master")] == [24]
    assert [d.months for d in find_durations("24 aylıq")] == [24]


@pytest.mark.parametrize("line", ["2 to 3 years", "2 - 3 years", "2—3 years"])
def test_spaced_and_worded_count_ranges_are_no_duration(line):
    assert find_durations(line) == []
