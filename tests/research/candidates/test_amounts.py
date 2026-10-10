import time
from decimal import Decimal

import pytest

from apps.research.candidates.amounts import find_amounts


def one(line):
    found = find_amounts(line)
    assert len(found) == 1, found
    return found[0]


def test_a_single_amount_with_its_currency():
    a = one("Monthly stipend: 43,000 HUF for 12 months")
    assert (a.low, a.high, a.currency, a.bound) == (Decimal(43000), Decimal(43000), "HUF", None)


def test_ranges_in_four_languages_are_one_candidate():
    assert one("50만원~150만원").bound == "range"
    a = one("Les montants tournent entre 1 200 et 2 100 € par mois")
    assert (a.low, a.high, a.currency, a.bound) == (Decimal(1200), Decimal(2100), "EUR", "range")
    a = one("¥143,000～145,000")
    assert (a.low, a.high, a.bound) == (Decimal(143000), Decimal(145000), "range")
    a = one("стипендия от 10 000 до 20 000 рублей")
    assert (a.low, a.high, a.currency, a.bound) == (Decimal(10000), Decimal(20000), "RUB", "range")
    a = one("EUR 1 000 – 2 000 per month")
    assert (a.low, a.high, a.bound) == (Decimal(1000), Decimal(2000), "range")


def test_and_lists_amounts_unless_a_lead_makes_it_a_range():
    assert [a.low for a in find_amounts("müvafiq olaraq 300 və 500 manat")] == [300, 500]
    assert [a.low for a in find_amounts("aylıq 110, 160 və 200 manat")] == [110, 160, 200]
    assert one("between 500 and 800 TL").bound == "range"
    assert one("500 ile 800 TL arasında").bound == "range"


def test_different_currencies_or_a_falling_pair_never_merge():
    found = find_amounts("a grant of 500 TRY and 20 AZN")
    assert [a.text for a in found] == ["500 TRY", "20 AZN"]
    assert [a.bound for a in find_amounts("500 TRY – 20 AZN")] == [None, None]
    assert [a.bound for a in find_amounts("2 000 € – 1 000 €")] == [None, None]


def test_approximations_are_code_s():
    assert one("aylıq təxminən 100 manat təqaüd").bound == "approximately"
    assert one("250만원 내외").bound == "approximately"
    assert one("about £1,500 a term").bound == "approximately"


def test_a_parenthesised_conversion_points_at_its_amount():
    found = find_amounts("HUF 65,000 (approx. 180 EUR)")
    assert len(found) == 2 and found[1].converted_from == 0 and found[1].currency == "EUR"
    # the same currency in brackets is an alternative figure, not a conversion
    found = find_amounts("1,300 euros (1,400 euros beginning with February 2026)")
    assert [a.converted_from for a in found] == [None, None]


def test_multipliers_and_other_scripts():
    assert one("50만원").low == Decimal(500000)
    assert one("1,5 млн руб.").low == Decimal(1500000)
    assert one("3 bin TL").low == Decimal(3000)
    assert one("١٢٠٠ €").low == Decimal(1200)
    assert one("1,5 €").low is None  # one digit after a comma, no multiplier: ambiguous
    assert one("3000 (üç min) manat").low == Decimal(3000)
    assert one("aylık 600,- TL").low == Decimal(600)


def test_grades_and_bare_numbers_are_not_amounts():
    assert find_amounts("minimum 71 bal, GPA 3.5") == []
    assert find_amounts("Founded in 1998 with 12,000 students") == []


def test_a_currency_word_never_ends_another_word():
    assert find_amounts("EMBO Doktora Sonrası Araştırma Bursları 2027 Yılı") == []
    assert find_amounts("burs bitiş tarihini izleyen 1 ay içerisinde") == []


def test_an_ambiguous_currency_form_names_no_currency():
    # "$" and "manat" are listed for several currencies: the figure stays, the currency does not
    a = one("$5,000 per year")
    assert a.low == Decimal(5000) and a.currency is None
    a = one("ayda 200 manat")
    assert a.currencies == frozenset({"AZN", "TMT"}) and a.currency is None


def test_long_runs_of_digits_stay_linear():
    for line in ("1 " * 2000, "1.2.3.4.5.6.7.8.9." * 230, "1 000 EUR, " * 400):
        started = time.perf_counter()
        find_amounts(line)
        assert time.perf_counter() - started < 0.05, line[:20]


def test_a_year_span_before_an_amount_is_not_an_amount():
    for line in ("from 2020 to 2021 500 EUR", "2026–2027 500 EUR", "for 2026-27 EUR 500",
                 "2026-2027 EUR 500", "2026-2027: EUR 500"):
        a = one(line)
        assert (a.low, a.currency, a.bound) == (Decimal(500), "EUR", None), line
    a = one("1 000–1 500 AZN")
    assert (a.low, a.high, a.bound) == (Decimal(1000), Decimal(1500), "range")
    assert one("2000-2100 EUR per month").bound == "range"


def test_a_thin_space_group_is_read():
    assert one("10\u2009000 €").low == Decimal(10000)


def test_approximation_signs_and_conversions():
    for line in ("≈ 300 EUR", "~300 EUR", "≈ $300"):
        assert one(line).bound == "approximately", line
    found = find_amounts("EUR 500 (≈ USD 540)")
    assert found[1].converted_from == 0 and found[1].bound is None


def test_won_amounts():
    assert one("1,000,000원").currency == "KRW"
    assert one("50만원").currency == "KRW"


@pytest.mark.parametrize("line, value, currency", [
    ("Year 1 – €12,000", "12000", "EUR"),
    ("Year 1 - £5,000 bursary", "5000", "GBP"),
    ("Category 3 - 500 EUR per month", "500", "EUR"),
    ("Room 101 - 300 EUR", "300", "EUR"),
    ("Intake 2026 – €12,000 per year", "12000", "EUR"),
])
def test_a_label_figure_never_joins_a_range(line, value, currency):
    amount = one(line)
    assert (amount.low, amount.high, amount.currency, amount.bound) == (
        Decimal(value), Decimal(value), currency, None)


@pytest.mark.parametrize("line, values", [
    ("€10,000 in 2026 and €12,000 in 2027", ["10000", "12000"]),
    ("EUR 500 for 2026, EUR 600 for 2027", ["500", "600"]),
])
def test_a_year_never_joins_a_list(line, values):
    assert [a.low for a in find_amounts(line)] == [Decimal(v) for v in values]
    assert all(a.currency == "EUR" for a in find_amounts(line))


@pytest.mark.parametrize("line, low, high", [
    ("1 000–1 500 AZN", "1000", "1500"),
    ("between 300 and 500 manat", "300", "500"),
    ("€1.2 million–€2 million", "1200000", "2000000"),
    ("Stipend: 800 - 1,200 EUR", "800", "1200"),
    ("800–1,200 EUR", "800", "1200"),
])
def test_real_ranges_stay_ranges(line, low, high):
    amount = one(line)
    assert (amount.bound, amount.low, amount.high) == ("range", Decimal(low), Decimal(high))


@pytest.mark.parametrize("line, low, high", [
    ("Stipend 800–1,200 EUR", "800", "1200"),
    ("Monthly stipend 800–1,200 EUR", "800", "1200"),
    ("Fees are 800–1,200 EUR", "800", "1200"),
    ("costs 800 - 1200 EUR", "800", "1200"),
    ("approximately 800–1,200 EUR", "800", "1200"),
    ("Tuition 5000 - 7000 USD", "5000", "7000"),
    ("Tuition fee 5000-7000 USD per year", "5000", "7000"),
    ("Tuition per year 5000-7000 USD", "5000", "7000"),
    ("Bursary 2,000 – 3,000 GBP", "2000", "3000"),
    ("Aylıq təqaüd 300-500 manat", "300", "500"),
    ("Стипендия 10 000–15 000 руб", "10000", "15000"),
])
def test_a_range_after_an_ordinary_word_stays_a_range(line, low, high):
    amount = one(line)
    assert (amount.low, amount.high) == (Decimal(low), Decimal(high))
    assert amount.bound in ("range", "approximately")


@pytest.mark.parametrize("line, value", [
    ("No. 3 - 500 EUR", "500"), ("#3 - 500 EUR", "500"),
    ("Kateqoriya 3 - 500 manat", "500"), ("Категория 3 - 500 руб", "500"),
])
def test_more_labels_never_join(line, value):
    assert one(line).low == Decimal(value)
