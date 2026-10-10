import pytest

from apps.research.candidates.dates import find_dates


def parts(line):
    found = find_dates(line)
    assert len(found) == 1, found
    d = found[0]
    return (d.year, d.month, d.day, d.end_year, d.end_month, d.end_day)


def test_absolute_dates_in_several_languages():
    assert parts("Deadline: 15 March 2026") == (2026, 3, 15, None, None, None)
    assert parts("до 1 февраля 2027 г.") == (2027, 2, 1, None, None, None)
    assert parts("Son müraciət tarixi - 20 may 2026") == (2026, 5, 20, None, None, None)
    assert parts("Başvurular 15 Ocak 2026'da sona erer") == (2026, 1, 15, None, None, None)
    assert parts("2026年3月15日まで") == (2026, 3, 15, None, None, None)
    assert parts("2026. február 15.") == (2026, 2, 15, None, None, None)
    assert parts("2026-03-15") == (2026, 3, 15, None, None, None)


def test_month_year_is_never_clipped_to_a_day():
    assert parts("Applications open in February 2027") == (2027, 2, None, None, None, None)


def test_ranges_are_one_candidate():
    assert parts("с 1 февраля по 31 июля 2026 года") == (2026, 2, 1, 2026, 7, 31)
    assert parts("Applications: 1–15 March 2026") == (2026, 3, 1, 2026, 3, 15)
    assert parts("müraciət tarixləri fevral-aprel aylarını əhatə edəcək") == (
        None, 2, None, None, 4, None)
    assert parts("Qəbul may-iyun aylarında") == (None, 5, None, None, 6, None)
    assert parts("접수기간: 3월 2일 ~ 3월 20일") == (None, 3, 2, None, 3, 20)


def test_suffix_ranges_in_azerbaijani_and_turkish():
    assert parts("Qeydiyyat 1 fevraldan 31 iyuladək davam edir") == (None, 2, 1, None, 7, 31)
    assert parts("Başvurular 15 Ocak'tan 15 Şubat'a kadar") == (None, 1, 15, None, 2, 15)


def test_and_lists_dates_unless_a_lead_makes_it_a_range():
    assert len(find_dates("Deadlines: 1 April and 1 October 2026")) == 2
    assert len(find_dates("Исключение — декабрь и апрель")) == 2
    assert parts("apply between October and January") == (None, 10, None, None, 1, None)


def test_slash_dates_with_both_parts_under_13_are_ambiguous():
    d = find_dates("Deadline 10/11/2026")[0]
    assert d.order_ambiguous and d.year == 2026 and (d.first, d.second) == (10, 11)
    d = find_dates("Deadline 25/11/2026")[0]
    assert not d.order_ambiguous and (d.day, d.month) == (25, 11)
    d = find_dates("Son tarix 10.11.2026")[0]
    assert not d.order_ambiguous and (d.day, d.month) == (10, 11)
    d = find_dates("Deadline 10/11/2026 to 12/12/2026")[0]
    assert d.order_ambiguous and (d.end_first, d.end_second) == (12, 12)


def test_codes_grades_and_intakes_are_not_dates():
    assert find_dates("Направление 37.03.01 Психология") == []
    assert find_dates("Направление 09.03.01 Информатика") == []
    assert find_dates("minimum 71 bal") == []
    assert find_dates("2026/27 academic year") == []
    assert find_dates("Founded in 1998") == []
    assert find_dates("10 Marmara Üniversitesi") == []


def test_ordinary_words_are_not_months():
    assert find_dates("students may apply") == []
    assert find_dates("they march on campus") == []
    assert find_dates("MSc Renewable Energy; Enerji Sistemleri") == []
    assert find_dates("Gerekli belgeler listesi") == []


def test_qualified_and_prepositional_months():
    assert [d.month for d in find_dates("Results in late March or early April.")] == [3, 4]
    assert parts("Applications open in March") == (None, 3, None, None, None, None)


def test_a_numeric_month_day_in_cjk_without_year():
    assert parts("3월 15일 마감") == (None, 3, 15, None, None, None)


def test_a_bare_start_day_shares_the_end_months_range():
    assert parts("between 1 and 15 March") == (None, 3, 1, None, 3, 15)
    assert parts("from 1 to 15 March") == (None, 3, 1, None, 3, 15)
    assert parts("1 to 15 March 2026") == (2026, 3, 1, 2026, 3, 15)
    assert parts("с 1 по 15 марта") == (None, 3, 1, None, 3, 15)
    assert parts("1–15 March") == (None, 3, 1, None, 3, 15)


def test_a_bare_day_with_and_and_no_lead_is_a_list():
    found = find_dates("1 and 15 March")
    assert [(d.month, d.day) for d in found] == [(3, 1), (3, 15)]
    assert len(find_dates("15 March 2027 and 1 June 2027")) == 2
    assert len(find_dates("1 March and 15 April")) == 2


@pytest.mark.parametrize("line", ["Step 2 – 15 March 2027", "Round 2 to 15 March 2027"])
def test_a_label_number_never_starts_a_date_range(line):
    assert parts(line) == (2027, 3, 15, None, None, None)


def test_a_label_number_before_a_day_month():
    assert parts("Room 12 - 15 March") == (None, 3, 15, None, None, None)


@pytest.mark.parametrize("line, expected", [
    ("1–15 March", (None, 3, 1, None, 3, 15)),
    ("1 to 15 March 2026", (2026, 3, 1, 2026, 3, 15)),
    ("between 1 and 15 March", (None, 3, 1, None, 3, 15)),
    ("с 1 по 15 марта", (None, 3, 1, None, 3, 15)),
    ("from 1 to 15 March", (None, 3, 1, None, 3, 15)),
    ("1–15 March 2027", (2027, 3, 1, 2027, 3, 15)),
    ("December 2026 – February 2027", (2026, 12, None, 2027, 2, None)),
])
def test_real_date_ranges_stay_ranges(line, expected):
    assert parts(line) == expected


def test_a_list_of_two_days_stays_two_dates():
    assert [(d.month, d.day) for d in find_dates("1 and 15 March")] == [(3, 1), (3, 15)]


@pytest.mark.parametrize("line", ["31/02/2027", "2027-02-30", "31.02.2027"])
def test_an_impossible_day_is_dropped(line):
    # dropped, not clipped: no candidate rather than a wrong day
    assert find_dates(line) == []


def test_an_impossible_day_keeps_at_most_its_month():
    assert [(d.year, d.month, d.day) for d in find_dates("31 April 2027")] == [(2027, 4, None)]


def test_february_29_follows_the_leap_year():
    assert parts("29 February 2028") == (2028, 2, 29, None, None, None)
    assert [d.day for d in find_dates("29 February 2027")] == [None]
    assert parts("29 February") == (None, 2, 29, None, None, None)


def test_a_range_ending_before_it_starts_is_two_dates():
    found = find_dates("15 March 2027 – 10 January 2027")
    assert [(d.year, d.month, d.day, d.end_month) for d in found] == [
        (2027, 3, 15, None), (2027, 1, 10, None)]


@pytest.mark.parametrize("line, expected", [
    ("Applications 1–15 March", (None, 3, 1, None, 3, 15)),
    ("Deadline 1–15 March", (None, 3, 1, None, 3, 15)),
    ("Registration 1-15 March 2027", (2027, 3, 1, 2027, 3, 15)),
    ("Applications open 1–15 March", (None, 3, 1, None, 3, 15)),
    ("Qeydiyyat 1-15 mart", (None, 3, 1, None, 3, 15)),
    ("Регистрация 1–15 марта", (None, 3, 1, None, 3, 15)),
])
def test_a_range_after_an_ordinary_word_stays_a_range(line, expected):
    assert parts(line) == expected


def test_a_label_in_another_language_never_starts_a_range():
    assert parts("Mərhələ 2 – 15 mart") == (None, 3, 15, None, None, None)
