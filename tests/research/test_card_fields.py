"""The card's values, checked by code against the line they were copied from.

A reading copies text and picks a label; this module is where "1.200" becomes
twelve hundred and "2 years" becomes 24 months. Every case a page could print
ambiguously is pinned to NO number rather than a guessed one.
"""

from decimal import Decimal

import pytest

from apps.reference_data import ISO_4217_CODES
from apps.research.card_fields import (
    confirmed_currency,
    currencies_in,
    duration_months,
    evidence_rows,
    on_line,
    parse_amount,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("€1,200", Decimal("1200")),
        ("992 Euro", Decimal("992")),
        ("1.200 €", Decimal("1200")),
        ("1 500 AZN", Decimal("1500")),
        ("1 500 AZN", Decimal("1500")),
        ("CHF 1'200", Decimal("1200")),
        ("€1,200.50", Decimal("1200.50")),
        ("1.200,50 €", Decimal("1200.50")),
        ("12.000.000 TL", Decimal("12000000")),
        ("€10000", Decimal("10000")),
        ("٢٥٠٠ AZN", Decimal("2500")),
    ],
)
def test_one_figure_is_read_the_way_the_page_printed_it(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "full tuition",        # no figure at all
        "€800–1,200",          # a range is two figures
        "1.5 million euros",   # one digit after a mark: money's rules do not explain it
        "12,50,000 INR",       # lakh grouping -- refused, never guessed
        "1,200.000",           # two different marks in the whole part
        "€1,200 and €300",     # two amounts copied as one
    ],
)
def test_anything_but_one_unambiguous_figure_is_no_number(text):
    assert parse_amount(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("€1,200", {"EUR"}),
        ("992 Euro", {"EUR"}),
        ("1 500 AZN", {"AZN"}),
        ("₼500", {"AZN"}),
        ("5.000 TL", {"TRY"}),
        ("US$5,000", {"USD"}),
        ("CA$1,000", {"CAD"}),        # "a$" inside "ca$" is not the Australian sign
        ("5000元", {"CNY"}),           # a sign may touch its figure
        ("300 000 теңге", {"KZT"}),
        ("$5,000", set()),            # a dollar of which country: the page did not say
        ("1,000 manat", set()),       # Azerbaijani or Turkmen
        ("¥300,000", set()),          # yen or yuan
        ("€1,000 or US$1,100", {"EUR", "USD"}),
        ("원서 접수", set()),          # "application form", not won
        ("100 EUR 원서", {"EUR"}),
        ("1,000,000원", {"KRW"}),
        ("50만원", {"KRW"}),
        ("50 만 원", {"KRW"}),
    ],
)
def test_a_currency_is_what_the_copy_names_and_nothing_ambiguous(text, expected):
    assert currencies_in(text) == frozenset(expected)


def test_a_currency_is_confirmed_only_when_the_copy_names_it_alone():
    assert confirmed_currency("EUR", "€1,200") == "EUR"
    assert confirmed_currency("USD", "$5,000") is None            # not evidenced
    assert confirmed_currency("GBP", "€1,200") is None            # the copy names another
    assert confirmed_currency("EUR", "€1,000 or US$1,100") is None  # names two
    assert confirmed_currency("UNSTATED", "€1,200") is None


@pytest.mark.parametrize(
    ("text", "unit", "expected"),
    [
        ("24 months", "MONTHS", 24),
        ("for up to 12 months", "MONTHS", 12),
        ("2 years", "YEARS", 24),
        ("24 ay", "MONTHS", 24),        # the unit is the readings'; the figure is code's
        ("two years", "YEARS", None),   # a number word keeps its text and gives no figure
        ("4 semesters", "OTHER", None),  # a semester is not a fixed number of months
        ("12-24 months", "MONTHS", None),  # a range
        ("200 months", "MONTHS", None),  # longer than any master's award runs
    ],
)
def test_months_come_from_the_one_figure_and_the_readings_unit(text, unit, expected):
    assert duration_months(text, unit) == expected


def test_a_copy_is_on_its_line_the_way_quotes_are_compared():
    line = "Scholars receive  €1,200 per month for 24 months."
    assert on_line("€1,200", line)
    assert on_line("24 MONTHS", line)   # case and whitespace do not count, as for quotes
    assert not on_line("€1,300", line)
    assert not on_line("", line)


def test_every_evidence_row_names_a_real_currency_and_is_reviewable():
    rows = evidence_rows()
    assert rows, "the evidence file is empty"
    for row in rows:
        assert row.currency in ISO_4217_CODES, row
        assert row.kind in ("symbol", "name", "abbreviation"), row
        assert row.review_status in ("drafted", "reviewed"), row
    pairs = [(row.form.casefold(), row.currency) for row in rows]
    assert len(pairs) == len(set(pairs)), "a form is listed twice for one currency"
