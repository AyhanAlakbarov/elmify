from datetime import date

from apps.documents.transcript import Highlight, Reading, Row, TranscriptContent
from apps.documents.transcript_checks import highlights, key_numbers


def _course(index, title, credits, status="COMPLETED", grade="80"):
    return Row(index, "course", title, credits, grade, status)


def _row(index, kind, credits=""):
    return Row(index, kind, "", credits, "", None)


def _reading(*rows, total_line=None, doubts=(), grade="88", scale="100", **content):
    return Reading(
        content=TranscriptContent(
            institution="Baku State University",
            overall_grade=grade,
            grading_scale=scale,
            credit_unit="ECTS",
            expected_completion=date(2027, 6, 30),
            **content,
        ),
        rows=rows,
        total_credits_line=total_line,
        doubts=doubts,
    )


def _two_semesters(first_total="11", overall="31"):
    return (
        _row(0, "semester_heading"),
        _course(1, "Organic Chemistry I", "6"),
        _course(2, "Programming", "5"),
        _row(3, "semester_total", first_total),
        _row(4, "semester_heading"),
        _course(5, "Physical Chemistry", "5"),
        _course(6, "Thesis", "15", status="IN_PROGRESS", grade=""),
        _row(7, "semester_total", "20"),
        _row(8, "overall_total", overall),
    )


def test_totals_that_add_up_raise_nothing():
    assert highlights(_reading(*_two_semesters())) == ()


def test_a_dropped_row_fails_its_semester_and_the_overall_total():
    rows = [row for row in _two_semesters() if row.index != 2]  # OCR dropped "Programming"
    assert highlights(_reading(*rows)) == (
        Highlight(kind="credit_total_mismatch", scope="semester", ref="3"),
        Highlight(kind="credit_total_mismatch", scope="transcript", ref="8"),
    )


def test_two_courses_merged_into_one_row_fail_the_total():
    """BEUN's failure mode: two courses on one row carrying one set of credits."""
    rows = (
        _course(0, "Organic Chemistry I Programming", "6"),
        _row(1, "semester_total", "11"),
    )
    assert Highlight(kind="credit_total_mismatch", scope="semester", ref="1") in highlights(
        _reading(*rows)
    )


def test_a_transcript_printing_no_total_says_not_checked_never_clean():
    rows = (_course(0, "Organic Chemistry I", "6"), _course(1, "Programming", "5"))
    assert highlights(_reading(*rows)) == (
        Highlight(kind="credit_total_not_checked", scope="transcript"),
    )


def test_a_total_counting_completed_courses_only_passes():
    rows = (
        _course(0, "Programming", "5", status="SUPERSEDED_ATTEMPT", grade="FF"),
        _course(1, "Programming", "5"),
        _course(2, "Thesis", "15", status="IN_PROGRESS", grade=""),
        _row(3, "overall_total", "5"),
    )
    assert highlights(_reading(*rows)) == ()


def test_a_total_printed_outside_the_table_is_checked_too():
    rows = (_course(0, "Organic Chemistry I", "6"),)
    assert highlights(_reading(*rows, total_line="240")) == (
        Highlight(kind="credit_total_mismatch", scope="transcript", ref="total_credits"),
    )


def test_a_grade_above_its_scale_is_highlighted_and_one_within_it_is_not():
    rows = (_course(0, "Organic Chemistry I", "6"), _row(1, "overall_total", "6"))
    assert highlights(_reading(*rows, grade="150", scale="100")) == (
        Highlight(kind="grade_above_scale", scope="field", ref="overall_grade"),
    )
    assert highlights(_reading(*rows, grade="3,45", scale="4.00")) == ()


def test_a_sixty_credit_course_is_out_of_range():
    rows = (_course(0, "Organic Chemistry I", "60"), _row(1, "overall_total", "60"))
    assert highlights(_reading(*rows)) == (
        Highlight(kind="credit_out_of_range", scope="row", ref="0"),
    )


def test_a_word_mixing_latin_and_cyrillic_letters_is_highlighted():
    rows = (
        _course(0, "Rуsсkий язык", "5"),  # the у and с are Cyrillic
        _course(1, "Azərbaycan tarixi", "5"),  # ə is a Latin letter
        _course(2, "Русский язык", "5"),
        _row(3, "overall_total", "15"),
    )
    assert highlights(_reading(*rows, field="Хiмия")) == (
        Highlight(kind="mixed_script", scope="field", ref="field"),
        Highlight(kind="mixed_script", scope="row", ref="0"),
    )


def test_an_unsure_answer_is_listed_once_after_the_checks():
    doubt = Highlight(kind="unsure", scope="row", ref="1")
    rows = (_course(0, "Organic Chemistry I", "6"),)
    assert highlights(_reading(*rows, doubts=(doubt, doubt))) == (
        Highlight(kind="credit_total_not_checked", scope="transcript"),
        doubt,
    )


def test_a_failed_check_is_shown_never_repaired():
    rows = (_course(0, "Organic Chemistry I", ""), _row(1, "overall_total", "6"))
    reading = _reading(*rows)
    assert highlights(reading) == (
        Highlight(kind="credit_total_mismatch", scope="transcript", ref="1"),
    )
    assert reading.rows[0].credits == ""  # the missing credit is not filled from the total


def test_the_key_numbers_are_the_printed_ones():
    numbers = key_numbers(_reading(*_two_semesters()))
    assert numbers.model_dump() == {
        "overall_grade": "88",
        "grading_scale": "100",
        "total_credits": "31",
        "total_credits_printed": True,
        "credit_unit": "ECTS",
        "graduation_date": date(2027, 6, 30),
    }


def test_without_a_printed_total_the_key_number_is_our_sum_and_says_so():
    rows = (
        _course(0, "Organic Chemistry I", "6"),
        _course(1, "Programming", "5,5"),
        _course(2, "Thesis", "15", status="IN_PROGRESS", grade=""),
    )
    numbers = key_numbers(_reading(*rows))
    assert (numbers.total_credits, numbers.total_credits_printed) == ("11.5", False)
