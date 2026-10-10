import json
from datetime import date
from decimal import Decimal

import pytest
from django.test import override_settings

from apps.documents.models import VerifiedFact
from apps.documents.ocr import OcrPage
from apps.documents.transcript import (
    Highlight,
    TranscriptContent,
    TranscriptCourse,
    TranscriptReadingDisabled,
    academic_record,
    check_gates,
    number,
    personal_names,
    read_from_pages,
)
from apps.research.decisions import Answer, DecisionsUnavailable
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _jev_launch_gate_open(settings):
    """Every test in this module reads a transcript, and TRANSCRIPT_JEV_ENABLED
    defaults off (the DPA/terms launch gate, spec 3.1) -- opened here so the
    reader tests below exercise the reading itself, not the gate. The gate's
    own refusal is asserted separately, with it explicitly closed.
    TRANSCRIPT_AZURE_ENABLED is opened for the same reason."""
    settings.TRANSCRIPT_JEV_ENABLED = True
    settings.TRANSCRIPT_AZURE_ENABLED = True

_PDF = b"%PDF-1.7 a transcript"
HEADER = ("Code", "Course", "Credits", "Grade")
LINES = (
    "Baku State University",
    "Bachelor of Science",
    "Field of study: Chemistry",
    "GPA 88 / 100",
    "Expected graduation 30.06.2027",
)
COURSES = (
    HEADER,
    ("", "Semester 1", "", ""),
    ("CHEM101", "Organic Chemistry I", "6", "91"),
    ("CS100", "Programming", "5", "FF"),
    ("", "Total", "11", ""),
    ("", "Semester 2", "", ""),
    ("CS100", "Programming", "5", "80"),
    ("CHEM400", "Thesis", "15", "in progress"),
    ("", "Total", "20", ""),
)


def _page(*tables, lines=LINES):
    return OcrPage(
        lines=tuple(lines),
        tables=tuple(tuple(tuple(row) for row in table) for table in tables),
    )


_COLUMN_KINDS = {
    "Code": "course_code",
    "Course": "course_title",
    "Credits": "credits",
    "Grade": "grade",
    "Fənlərin adı": "course_title",
    "Kreditlər": "credits",
    "Saatlar": "hours",
    "Qiymətlər": "grade",
}


def _inspected(state, question):
    """What a question's `inspect` path points at, looked up by key the way Jev has to find it.

    A list position is refused, not resolved: Jev loses its place in a long list and answers
    about a neighbour (measured 2026-09-26 -- see transcript_questions.py).
    """
    target = state
    for key in question.inspect.strip("`").split("."):
        assert isinstance(target, dict) and key in target, f"not a keyed path: {question.inspect}"
        target = target[key]
    return target


def _answer(state, qid, question):
    """What a careful reader of these fixtures answers. Test scaffolding, not a model of Jev."""
    name = qid.partition(":")[0]
    if name == "column":
        return _COLUMN_KINDS.get(_inspected(state, question)[0], "other")
    if name in ("kind", "in_progress", "failed"):
        cells = _inspected(state, question)
        text = " ".join(cells)
        if name == "in_progress":
            return "in progress" in text
        if name == "failed":
            return "FF" in cells
        if text.strip().startswith("Semester") or sum(bool(cell) for cell in cells) == 1:
            return "semester_heading"
        if "Overall" in text:
            return "overall_total"
        if "Total" in text or "cəmi" in text:
            return "semester_total"
        return "header" if {"Course", "Fənlərin adı"} & set(cells) else "course"
    lines = {line["text"]: line["id"] for line in state["lines"]}
    numbers = {found["text"]: found["id"] for found in state["numbers"]}
    dates = {found["text"]: found["id"] for found in state["dates"]}
    return {
        "credit_system": "ECTS",
        "country": "AZ",
        "institution": lines.get("Baku State University", "none"),
        "qualification": lines.get("Bachelor of Science", "none"),
        "field": lines.get("Field of study: Chemistry", "none"),
        "overall_grade": numbers.get("88", "none"),
        "grading_scale": numbers.get("100", "none"),
        "total_credits": "none",
        "completed_on": "none",
        "expected_completion": dates.get("30.06.2027", "none"),
    }[qid]


def _jev(*, unsure=(), states=None):
    def call(state, questions, *, model, provider):
        if states is not None:
            states.append(state)
        answers = {}
        for qid, question in questions.items():
            value = _answer(state, qid, question)
            confidence = 0.4 if qid in unsure else 0.97
            answers[qid] = Answer(
                id=qid,
                value=value,
                confidence=confidence,
                probabilities={str(value): confidence},
                model=model,
                provider=provider,
            )
        return answers

    return call


def _read(agency, student, fake_store, *pages, names=frozenset(), client=None):
    return read_from_pages(pages, names, client=client or _jev())


def test_every_value_is_a_printed_cell_or_line_jev_chose(agency_a, membership_a, fake_store):
    reading = _read(agency_a, membership_a, fake_store, _page(COURSES))
    content = reading.content
    assert (content.institution, content.qualification, content.field) == (
        "Baku State University",
        "Bachelor of Science",
        "Chemistry",
    )
    assert (content.overall_grade, content.grading_scale) == ("88", "100")
    assert content.credit_unit == "ECTS"
    assert content.country_code == "AZ"
    assert content.expected_completion == date(2027, 6, 30) and content.completed_on is None
    assert [(c.title, c.credits, c.grade, c.status) for c in content.courses] == [
        ("Organic Chemistry I", Decimal("6"), "91", "COMPLETED"),
        ("Programming", Decimal("5"), "FF", "SUPERSEDED_ATTEMPT"),
        ("Programming", Decimal("5"), "80", "COMPLETED"),
        ("Thesis", Decimal("15"), "in progress", "IN_PROGRESS"),
    ]
    assert reading.doubts == ()


def test_a_failed_course_never_retaken_is_kept_as_completed(agency_a, membership_a, fake_store):
    table = (HEADER, ("CS100", "Programming", "5", "FF"))
    [course] = _read(agency_a, membership_a, fake_store, _page(table)).content.courses
    assert course.status == "COMPLETED" and course.grade == "FF"


def test_a_transcript_is_never_written_to_the_shared_decision_cache(
    agency_a, membership_a, fake_store
):
    """DecisionRecord is shared-catalog data every tenant reads; a transcript is one student's."""
    from apps.research.models import DecisionRecord

    _read(agency_a, membership_a, fake_store, _page(COURSES))
    assert not DecisionRecord.objects.exists()


def test_academic_record_drops_the_superseded_attempt_and_converts_credits():
    content = TranscriptContent(
        institution="Baku State University",
        country_code="AZ",
        qualification="BSc",
        field="Chemistry",
        overall_grade="88",
        grading_scale="100",
        credit_unit="ECTS",
        courses=(
            TranscriptCourse(
                title="Programming", credits=Decimal(5), grade="FF", status="SUPERSEDED_ATTEMPT"
            ),
            TranscriptCourse(title="Programming", credits=Decimal(5), status="COMPLETED"),
            TranscriptCourse(title="Thesis", credits=Decimal(15), status="IN_PROGRESS"),
            TranscriptCourse(title="Misread", credits=Decimal(150), status="COMPLETED"),
        ),
        expected_completion=date(2027, 6, 30),
    )
    record = academic_record(content)
    assert [c["title"] for c in record["courses"]] == ["Programming", "Thesis", "Misread"]
    assert record["courses"][0]["ects"] == "5.00"
    assert record["courses"][1]["in_progress"] is True
    assert record["courses"][2]["ects"] is None  # a 150-credit course fails the range check
    assert record["expected_completion"] == "2027-06-30"


def test_nothing_identifying_the_student_reaches_jev(agency_a, membership_a, fake_store):
    lines = (
        "Family name: Aliyev",
        "Ali Aliyev",
        "Date of birth:",
        "01.05.2002",
        "Student No 20231234",
        *LINES,
    )
    table = (
        HEADER,
        ("Surname", "Aliyev", "", ""),
        ("", "Ali Aliyev", "", ""),
        ("1801101", "Ali riyaziyyat I", "6", "91"),
    )
    states = []
    reading = _read(
        agency_a,
        membership_a,
        fake_store,
        _page(table, lines=lines),
        names=frozenset({"ali", "aliyev"}),
        client=_jev(states=states),
    )
    sent = json.dumps(states, ensure_ascii=False)
    for personal in ("Aliyev", "01.05.2002", "20231234", "1801101"):
        assert personal not in sent
    # Two name words make a line personal, never one: "Ali" is also Azerbaijani for "higher".
    assert [course.title for course in reading.content.courses] == ["Ali riyaziyyat I"]


def test_a_name_the_document_labels_once_is_dropped_everywhere(agency_a, membership_a, fake_store):
    """The Russian specimen prints the name in its personal-data block and again, unlabelled, at
    the head of every page -- in Cyrillic, which no Latin account name would match."""
    pages = (
        _page(lines=("Фамилия Иванов Имя Иван Отчество Иванович", *LINES)),
        _page(COURSES, lines=("Иванов Иван Иванович", "Страница 2")),
    )
    states = []
    _read(agency_a, membership_a, fake_store, *pages, client=_jev(states=states))
    assert "Иванов" not in json.dumps(states, ensure_ascii=False)


def test_a_capitalised_turkic_surname_is_recognised_despite_the_dotted_i(
    agency_a, membership_a, fake_store
):
    """"ALİYEV".casefold() inserts a combining dot above and splits the word into "ali"/"yev",
    matching neither of the account's plain "ali"/"aliyev" -- review round 1, item 1."""
    lines = ("ALİ ALİYEV", *LINES)
    table = (HEADER, ("", "ALİ ALİYEV", "", ""), ("1801101", "Ali riyaziyyat I", "6", "91"))
    states = []
    reading = _read(
        agency_a,
        membership_a,
        fake_store,
        _page(table, lines=lines),
        names=frozenset({"ali", "aliyev"}),
        client=_jev(states=states),
    )
    sent = json.dumps(states, ensure_ascii=False)
    assert "ALİYEV" not in sent and "ALİ ALİYEV" not in sent
    assert [course.title for course in reading.content.courses] == ["Ali riyaziyyat I"]


def test_a_label_ending_a_line_after_another_label_and_chained_label_only_lines_release_nothing(
    agency_a, membership_a, fake_store
):
    """Two labels on one line: only the LAST one ending the line should release the next line.
    Chained label-only lines: a line consumed as a value must still be checked as a label line,
    so a third line in a row of labels is not released either -- review round 1, item 2."""
    lines = (
        "Surname: Aliyev   Date of birth:",
        "01.05.2002",
        "Given name:",
        "Surname:",
        "Aliyev",
        *LINES,
    )
    states = []
    _read(
        agency_a,
        membership_a,
        fake_store,
        _page(COURSES, lines=lines),
        # Two words, matching how the account's own name is represented elsewhere in this file:
        # a lone "Aliyev" is not itself enough to drop a line (see the "Ali" comment above), so
        # this isolates the label-adjacency fix from name matching.
        names=frozenset({"ali", "aliyev"}),
        client=_jev(states=states),
    )
    sent = json.dumps(states, ensure_ascii=False)
    for personal in ("Aliyev", "01.05.2002"):
        assert personal not in sent


def test_a_label_on_its_own_line_teaches_a_name_reused_unlabelled_on_another_page(
    agency_a, membership_a, fake_store
):
    """The Russian specimen sometimes prints a label alone, with its value on the next line --
    not on the same line, which is all the original leak test covered -- review round 1, item 3."""
    pages = (
        _page(lines=("Фамилия:", "Иванов", *LINES)),
        _page(COURSES, lines=("Иванов Иван Иванович", "Страница 2")),
    )
    states = []
    _read(agency_a, membership_a, fake_store, *pages, client=_jev(states=states))
    assert "Иванов" not in json.dumps(states, ensure_ascii=False)


def test_a_label_row_drops_the_value_row_below_it_including_a_birth_date(
    agency_a, membership_a, fake_store
):
    """A header-row-of-labels over a value row is a common table layout; the value row must drop
    whole, not only when its spelling happens to match the account -- review round 1, item 3."""
    personal_table = (
        ("Surname", "Name", "Date of birth", "Student ID"),
        # A spelling that differs from the account's own -- the row must drop regardless.
        ("Aliev", "Ali", "01.05.2002", "20231234"),
    )
    states = []
    reading = _read(
        agency_a,
        membership_a,
        fake_store,
        _page(personal_table, COURSES),
        names=frozenset({"ali", "aliyev"}),
        client=_jev(states=states),
    )
    sent = json.dumps(states, ensure_ascii=False)
    for personal in ("Aliev", "01.05.2002", "20231234"):
        assert personal not in sent
    assert [course.title for course in reading.content.courses] == [
        "Organic Chemistry I",
        "Programming",
        "Programming",
        "Thesis",
    ]


def test_an_exam_date_column_does_not_drop_the_course_rows(agency_a, membership_a, fake_store):
    """A table row holding a full date is masked, not dropped -- review round 2, item 1. Dropping
    the whole row on any date match emptied every course after the first exam-date column."""
    table = (
        (*HEADER, "Exam date"),
        ("CHEM101", "Organic Chemistry I", "6", "91", "15.02.2023"),
        ("CS100", "Programming", "5", "80", "20.06.2023"),
    )
    states = []
    reading = _read(agency_a, membership_a, fake_store, _page(table), client=_jev(states=states))
    assert [course.title for course in reading.content.courses] == [
        "Organic Chemistry I",
        "Programming",
    ]
    sent = json.dumps(states, ensure_ascii=False)
    assert "15.02.2023" not in sent and "20.06.2023" not in sent


def test_an_exam_date_column_in_cyrillic_with_an_iso_date_does_not_drop_the_row(
    agency_a, membership_a, fake_store
):
    """The same masking, an ISO-format date under a Cyrillic column header."""
    table = (
        (*HEADER, "Дата"),
        ("CHEM101", "Organic Chemistry I", "6", "91", "2023-01-20"),
    )
    states = []
    reading = _read(agency_a, membership_a, fake_store, _page(table), client=_jev(states=states))
    assert [course.title for course in reading.content.courses] == ["Organic Chemistry I"]
    assert "2023-01-20" not in json.dumps(states, ensure_ascii=False)


def test_a_decomposed_dotted_i_still_folds_to_the_same_letter(agency_a, membership_a, fake_store):
    """OCR may emit İ as a plain "I" followed by its own combining dot above (Unicode NFD)
    rather than the precomposed character; `\\w+` treats the combining mark as a word boundary
    and still splits the surname in two before `_fold` ever runs, unless the text is first
    composed to NFC -- review round 2, item 2 (controller-promoted, privacy)."""
    decomposed = "ALİYEV"  # "ALİYEV" with İ spelled as "I" + U+0307 COMBINING DOT ABOVE
    lines = (f"ALİ {decomposed}", *LINES)
    table = (
        HEADER,
        ("", f"ALİ {decomposed}", "", ""),
        ("1801101", "Ali riyaziyyat I", "6", "91"),
    )
    states = []
    reading = _read(
        agency_a,
        membership_a,
        fake_store,
        _page(table, lines=lines),
        names=frozenset({"ali", "aliyev"}),
        client=_jev(states=states),
    )
    sent = json.dumps(states, ensure_ascii=False)
    assert "ALİ" not in sent
    assert [course.title for course in reading.content.courses] == ["Ali riyaziyyat I"]


@override_settings(DECISIONS_PROVIDER={"default": "adapter:openai"})
def test_transcript_decisions_never_route_through_a_non_typesafe_provider(
    agency_a, membership_a, fake_store
):
    """A configuration that maps decisions to an adapter by default -- for other decisions --
    must never let a transcript's minimised content reach anything but TypeSafe (spec T19)."""
    with pytest.raises(DecisionsUnavailable):
        check_gates()


def test_transcript_reading_is_refused_until_the_jev_launch_gate_is_on(
    agency_a, membership_a, fake_store, settings
):
    """Launch gate (spec 3.1): real students' transcripts go to Jev, through
    OpenRouter, only after TypeSafe's DPA is accepted and OpenRouter's terms are
    reviewed. Checked in code, next to the typesafe-provider check, so a document
    is never even opened while the gate is closed. A distinct exception from the
    provider-routing DecisionsUnavailable above: transcript_pages.read_upload catches this
    one and fails the upload immediately, because unlike a provider that did not answer, a
    closed gate cannot be fixed by a retry (tests/documents/test_transcript_worker.py)."""
    settings.TRANSCRIPT_JEV_ENABLED = False
    with pytest.raises(TranscriptReadingDisabled):
        check_gates()


def test_an_out_of_list_country_answer_is_treated_as_unsure(agency_a, membership_a, fake_store):
    def call(state, asked, *, model, provider):
        answers = {}
        for qid, question in asked.items():
            value = "ZZ" if qid == "country" else _answer(state, qid, question)
            answers[qid] = Answer(
                id=qid,
                value=value,
                confidence=0.97,
                probabilities={str(value): 0.97},
                model=model,
                provider=provider,
            )
        return answers

    reading = _read(agency_a, membership_a, fake_store, _page(COURSES), client=call)
    assert reading.content.country_code == ""
    assert Highlight(kind="unsure", scope="field", ref="country") in reading.doubts


def test_a_second_credits_column_does_not_split_the_table(agency_a, membership_a, fake_store):
    """NKU prints ECTS and local credits side by side; the first is the one read."""
    table = (("Code", "Course", "Credits", "Credits", "Grade"), ("C1", "Physics I", "6", "4", "BA"))
    [course] = _read(agency_a, membership_a, fake_store, _page(table)).content.courses
    assert (course.credits, course.grade) == (Decimal("6"), "BA")


def test_two_course_name_columns_side_by_side_read_each_course_once(
    agency_a, membership_a, fake_store
):
    """A bilingual supplement prints the course name twice, one column per language. A title
    column holding no credits or grade does not start a block: split there, every course was
    read twice, half the copies without credits, and every credit total still matched."""
    table = (
        ("Fənlərin adı", "Course", "Kreditlər", "Qiymətlər"),
        ("Kimya", "Chemistry", "6", "A"),
        ("Fizika", "Physics", "5", "B"),
    )
    reading = _read(agency_a, membership_a, fake_store, _page(table, lines=()))
    assert [(c.title, c.credits, c.grade) for c in reading.content.courses] == [
        ("Kimya", Decimal("6"), "A"),
        ("Fizika", Decimal("5"), "B"),
    ]


def test_personal_names_come_from_the_account_and_from_the_cv(agency_a, membership_a):
    membership_a.user.first_name, membership_a.user.last_name = "Leyla", "Mammadova"
    membership_a.user.save()
    with tenant_scope(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Leyla Rauf qizi Mammadova"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            created_by=membership_a,
        )
        assert personal_names(membership_a) == {"leyla", "mammadova", "rauf", "qizi"}


def test_an_unsure_answer_becomes_a_highlight(agency_a, membership_a, fake_store):
    reading = _read(
        agency_a,
        membership_a,
        fake_store,
        _page(COURSES),
        client=_jev(unsure=("institution", "kind:2", "column:1")),
    )
    assert set(reading.doubts) == {
        Highlight(kind="unsure", scope="field", ref="institution"),
        Highlight(kind="unsure", scope="row", ref="2"),
        Highlight(kind="unsure", scope="transcript", ref="columns"),
    }


def test_two_semesters_printed_side_by_side_are_read_one_after_the_other(
    agency_a, membership_a, fake_store
):
    table = (
        (*HEADER, *HEADER),
        ("", "Semester 1", "", "", "", "Semester 2", "", ""),
        ("C1", "Physics I", "6", "80", "C2", "Physics II", "6", "75"),
        ("C3", "Algebra", "5", "70", "C4", "Analysis", "5", "72"),
        ("", "Total", "11", "", "", "Total", "11", ""),
    )
    reading = _read(agency_a, membership_a, fake_store, _page(table))
    assert [course.title for course in reading.content.courses] == [
        "Physics I",
        "Algebra",
        "Physics II",
        "Analysis",
    ]
    assert [row.kind for row in reading.rows] == [
        "header", "semester_heading", "course", "course", "semester_total",
    ] * 2


#: Invented, shaped like a phone photo of an Azerbaijani diploma supplement's course page
#: (2026-09-26): a year and a semester heading each print one cell, in the title column.
ELAVE = (
    ("N", "Fənlərin adı", "Kreditlər", "Saatlar", "Qiymətlər"),
    ("", "1 kurs", "", "", ""),
    ("", "I semestr", "", "", ""),
    ("1", "Ali riyaziyyat I", "6", "180", "73 bal (C)"),
    ("2", "Fizika I", "5", "150", "64 bal (D)"),
    ("", "I semestr üzrə cəmi", "11", "330", ""),
    ("", "II semestr", "", "", ""),
    ("3", "Fizika II", "5", "150", "82 bal (B)"),
)


def test_a_course_table_with_one_cell_headings_reads_every_course(
    agency_a, membership_a, fake_store
):
    """The live photo read no course at all (2026-09-26). Two causes, both pinned here: every
    question pointed Jev at a list position, and the title column's sample carried the headings.
    """
    states = []
    reading = _read(
        agency_a, membership_a, fake_store, _page(ELAVE, lines=()), client=_jev(states=states)
    )
    assert [(c.title, c.credits, c.grade) for c in reading.content.courses] == [
        ("Ali riyaziyyat I", Decimal("6"), "73 bal (C)"),
        ("Fizika I", Decimal("5"), "64 bal (D)"),
        ("Fizika II", Decimal("5"), "82 bal (B)"),
    ]
    # With "1 kurs" and "I semestr" in its sample, Jev read the title column as a semester
    # column in 4 runs of 4; with them left out, as course titles at 0.99-1.0 in 3 of 3.
    titles = states[0]["columns"]["c1"]["cells"]
    assert titles == [
        "Fənlərin adı", "Ali riyaziyyat I", "Fizika I", "I semestr üzrə cəmi", "Fizika II",
    ]


def test_rows_are_asked_forty_at_a_time(agency_a, membership_a, fake_store):
    table = (HEADER, *((f"C{i}", f"Course {i}", "5", "80") for i in range(90)))
    states = []
    reading = _read(agency_a, membership_a, fake_store, _page(table), client=_jev(states=states))
    assert len(reading.content.courses) == 90
    assert [len(state.get("rows", ())) for state in states] == [0, 40, 40, 11]


def test_a_printed_number_is_read_with_either_decimal_mark():
    assert number("7,5") == number("7.5") == Decimal("7.5")
    assert number("240") == Decimal("240")
    assert number("6 AKTS") is None and number("") is None


def _azure_page(rows, confidences, *, lines=LINES, source="azure"):
    return OcrPage(
        lines=tuple(lines),
        tables=(tuple(tuple(row) for row in rows),),
        cell_confidence=(tuple(tuple(c) for c in confidences),),
        source=source, api_version="2024-11-30" if source == "azure" else "",
    )


def _flagged(reading):
    by_index = {row.index: row.title for row in reading.rows}
    return sorted(by_index[int(h.ref)] for h in reading.doubts if h.kind == "low_confidence")


def test_a_doubtful_credit_flags_its_row(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("CHEM101", "Organic Chemistry I", "6", "91"), ("PHY101", "Physics", "5", "80")],
        [(0.99,) * 4, (0.99, 0.99, 0.62, 0.99), (0.99, 0.99, 0.97, 0.98)],
    )
    assert _flagged(_read(agency_a, membership_a, fake_store, page)) == ["Organic Chemistry I"]


def test_a_doubtful_grade_flags_its_row_too(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("PHY101", "Physics", "5", "80")],
        [(0.99,) * 4, (0.99, 0.99, 0.99, 0.41)],
    )
    assert _flagged(_read(agency_a, membership_a, fake_store, page)) == ["Physics"]


def test_a_doubtful_title_alone_raises_no_flag(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("PHY101", "Physics", "5", "80")],
        [(0.99,) * 4, (0.99, 0.30, 0.99, 0.99)],
    )
    assert _flagged(_read(agency_a, membership_a, fake_store, page)) == []


def test_blank_cells_carry_no_confidence_and_raise_no_flag(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("CHEM400", "Thesis", "", "")],
        [(0.99,) * 4, (0.99, 0.99, None, None)],
    )
    assert _flagged(_read(agency_a, membership_a, fake_store, page)) == []


def test_confidences_stay_aligned_when_a_row_is_dropped(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("", "Aysel Mammadova", "", ""), ("PHY101", "Physics", "5", "80")],
        [(0.99,) * 4, (0.40, 0.40, None, None), (0.99, 0.99, 0.55, 0.99)],
    )
    names = frozenset({"aysel", "mammadova"})
    reading = _read(agency_a, membership_a, fake_store, page, names=names)
    assert _flagged(reading) == ["Physics"]


def test_text_layer_cells_are_never_flagged(agency_a, membership_a, fake_store):
    page = _azure_page(
        [HEADER, ("PHY101", "Physics", "5", "80")],
        [(None,) * 4, (None,) * 4], source="text_layer",
    )
    assert _flagged(_read(agency_a, membership_a, fake_store, page)) == []


def test_transcript_reading_is_refused_until_the_azure_launch_gate_is_on(
    agency_a, membership_a, fake_store, settings
):
    settings.TRANSCRIPT_AZURE_ENABLED = False
    with pytest.raises(TranscriptReadingDisabled, match="TRANSCRIPT_AZURE_ENABLED"):
        check_gates()
