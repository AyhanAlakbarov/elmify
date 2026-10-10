"""Every date shape a CV actually prints, and what it must read as.

The rows are the specification. `docs/superpowers/research/2026-08-31-cv-extraction-baseline.md`
measured why this exists: asked for a `date`, the model returned 0944-09-01,
0200-01-01 and 0527-01-01 off text that plainly said "September 2020". Asking
it to copy the string and parsing here removes the class -- a parser cannot
garble a year it did not invent.
"""

from datetime import date

import pytest

from apps.documents.dates import Convention, date_convention, parse_cv_date

# (written, expected start, expected end)
FORMATS = [
    # ISO and partial ISO
    ("2020-09-01", date(2020, 9, 1), date(2020, 9, 1)),
    ("2020-09", date(2020, 9, 1), date(2020, 9, 30)),
    ("2020", date(2020, 1, 1), date(2020, 12, 31)),
    # month names, English
    ("September 2020", date(2020, 9, 1), date(2020, 9, 30)),
    ("Sept 2020", date(2020, 9, 1), date(2020, 9, 30)),
    ("Sep. 2020", date(2020, 9, 1), date(2020, 9, 30)),
    ("1 September 2020", date(2020, 9, 1), date(2020, 9, 1)),
    ("September 1, 2020", date(2020, 9, 1), date(2020, 9, 1)),
    # month names, the launch markets and their neighbours
    ("Eylül 2020", date(2020, 9, 1), date(2020, 9, 30)),       # Turkish
    ("Sentyabr 2020", date(2020, 9, 1), date(2020, 9, 30)),    # Azerbaijani
    ("März 2019", date(2019, 3, 1), date(2019, 3, 31)),        # German
    ("Oktober 2019", date(2019, 10, 1), date(2019, 10, 31)),
    ("septembre 2020", date(2020, 9, 1), date(2020, 9, 30)),   # French
    # unambiguous numerics
    ("09/2020", date(2020, 9, 1), date(2020, 9, 30)),
    ("9/2020", date(2020, 9, 1), date(2020, 9, 30)),
    ("2020/09", date(2020, 9, 1), date(2020, 9, 30)),
    ("25/09/2020", date(2020, 9, 25), date(2020, 9, 25)),      # 25 cannot be a month
    ("09/25/2020", date(2020, 9, 25), date(2020, 9, 25)),
    ("01.09.2020", date(2020, 9, 1), date(2020, 9, 1)),        # German dotted
    # seasons, northern hemisphere
    ("Fall 2020", date(2020, 9, 1), date(2020, 11, 30)),
    ("Autumn 2020", date(2020, 9, 1), date(2020, 11, 30)),
    ("Spring 2021", date(2021, 3, 1), date(2021, 5, 31)),
    ("Summer 2020", date(2020, 6, 1), date(2020, 8, 31)),
    ("Winter 2020", date(2020, 1, 1), date(2020, 2, 29)),
    # German semesters: WS runs 1 Oct - 31 Mar, SS runs 1 Apr - 30 Sep
    ("WS 2020/21", date(2020, 10, 1), date(2021, 3, 31)),
    ("Wintersemester 2020/21", date(2020, 10, 1), date(2021, 3, 31)),
    ("SS 2019", date(2019, 4, 1), date(2019, 9, 30)),
    ("Sommersemester 2019", date(2019, 4, 1), date(2019, 9, 30)),
]


@pytest.mark.parametrize("written,start,end", FORMATS)
def test_a_written_date_reads_as_its_start(written, start, end):
    assert parse_cv_date(written) == start


@pytest.mark.parametrize("written,start,end", FORMATS)
def test_a_written_date_reads_as_its_end_when_it_ends_a_range(written, start, end):
    assert parse_cv_date(written, position="end") == end


@pytest.mark.parametrize(
    "written", ["Present", "present", "Current", "ongoing", "to date", "—", "-", "now"]
)
def test_an_open_ended_range_has_no_end_date(written):
    """None renders as 'present' already -- see cv_dates.month_year's default."""
    assert parse_cv_date(written, position="end") is None


@pytest.mark.parametrize(
    "written",
    [
        "0944-09-01",   # measured, twice in three runs, off text saying September 2020
        "0200-01-01",
        "0527-01-01",
        "2999-01-01",
        "",
        "   ",
        "n/a",
        "see attached",
        "2020-13-01",   # no thirteenth month
        "32/01/2020",   # no thirty-second day
    ],
)
def test_a_date_that_cannot_be_read_is_none_rather_than_a_guess(written):
    """None becomes a gap question. A wrong year that looks plausible does not,
    which is the whole reason this function exists."""
    assert parse_cv_date(written) is None


def test_a_date_object_passes_straight_through():
    assert parse_cv_date(date(2020, 9, 1)) == date(2020, 9, 1)


class TestAmbiguousNumerics:
    """01/09/2020 is 1 September to a European and 9 January to an American."""

    def test_day_first_by_default(self):
        assert parse_cv_date("01/09/2020") == date(2020, 9, 1)

    def test_month_first_when_the_convention_says_so(self):
        token = date_convention.set(Convention.MONTH_FIRST)
        try:
            assert parse_cv_date("01/09/2020") == date(2020, 1, 9)
        finally:
            date_convention.reset(token)

    def test_an_unambiguous_date_ignores_the_convention(self):
        token = date_convention.set(Convention.MONTH_FIRST)
        try:
            assert parse_cv_date("25/09/2020") == date(2020, 9, 25)
        finally:
            date_convention.reset(token)


class TestConventionFromTheDocument:
    """The page outranks the passport: an Azerbaijani who studied in Boston
    writes American dates, and the document shows it while nationality does not."""

    def test_a_day_over_twelve_proves_day_first(self):
        from apps.documents.dates import convention_from_text

        assert convention_from_text("Internship 25/09/2020 - 01/02/2021") is Convention.DAY_FIRST

    def test_a_month_first_date_proves_month_first(self):
        from apps.documents.dates import convention_from_text

        assert convention_from_text("Internship 09/25/2020 - 02/01/2021") is Convention.MONTH_FIRST

    def test_a_document_with_no_evidence_says_nothing(self):
        from apps.documents.dates import convention_from_text

        assert convention_from_text("September 2020 - February 2021") is None


class TestResolvingTheConvention:
    """Document first, nationality second, day-first last."""

    def test_the_document_outranks_the_passport(self):
        from apps.documents.dates import resolve_convention

        assert resolve_convention("Intern 09/25/2020", nationality="AZ") is Convention.MONTH_FIRST

    def test_nationality_decides_when_the_document_is_silent(self):
        from apps.documents.dates import resolve_convention

        silent = "September 2020 - February 2021"
        assert resolve_convention(silent, nationality="US") is Convention.MONTH_FIRST
        assert resolve_convention(silent, nationality="TR") is Convention.DAY_FIRST

    def test_day_first_when_nothing_is_known(self):
        from apps.documents.dates import resolve_convention

        assert resolve_convention("September 2020", nationality=None) is Convention.DAY_FIRST
