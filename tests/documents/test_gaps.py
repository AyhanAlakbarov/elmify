from datetime import date

import pytest

from apps.documents import gaps
from apps.documents.gap_intake import field_name
from apps.documents.gaps import (
    _CERTIFICATES_NOTE,
    GapQuestion,
    Kind,
    UnanswerableQuestion,
    absent_sections,
    answer_questions,
    education_completeness,
    gap_notes,
    gap_questions,
    incomplete_entry,
    missing_award,
    missing_contact,
    missing_degree_detail,
    missing_grade,
    missing_language_detail,
    missing_medium_of_instruction,
    missing_publication_detail,
    programme_required,
    timeline_gaps,
)
from apps.documents.models import VerifiedFact
from apps.documents.schemas import TIMELINE_STATEMENT_MAX
from apps.documents.verification import unsuperseded_facts
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

from .conftest import make_fact

pytestmark = pytest.mark.django_db


@pytest.fixture
def student(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="gap-student")
        yield Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )


def test_a_missing_orcid_is_a_question(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})

    questions = missing_contact(student)

    assert [q.payload_key for q in questions if q.payload_key == "orcid"] == ["orcid"]


def test_a_handle_recovered_from_the_pdf_is_not_asked_for_again(student):
    """extract_link_urls recovers addresses from PDF link annotations, and a CV
    that hyperlinks a handle is not missing anything. Asking for something
    already on file is the fastest way to make a student distrust the tool.
    """
    make_fact(
        student,
        VerifiedFact.Category.IDENTITY,
        {"full_name": "A Student", "github_username": "0rkhann"},
    )

    assert "github_url" not in {q.payload_key for q in missing_contact(student)}


def test_a_student_with_no_identity_fact_is_asked_nothing(student):
    """No IDENTITY row means the CV was never ingested. Questions about a
    contact header that does not exist yet are noise, not a gap.
    """
    assert missing_contact(student) == ()


_DEGREE = {
    "degree_as_awarded": "BSc Petroleum Engineering",
    "institution_original": "Example University",
    "start_date": "2020-09-01",
    "end_date": "2024-06-30",
}


def test_a_degree_with_no_grade_is_a_question(student):
    """For a graduate application the grade is expected, not optional."""
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))

    questions = missing_grade(student)

    assert [q.payload_key for q in questions] == ["grade_native"]
    assert "BSc Petroleum Engineering" in questions[0].evidence


def test_a_degree_still_in_progress_is_asked_when_it_ends(student):
    """R-040 (cv-rules.csv, BINDING, universal): an in-progress degree states
    its expected graduation date. Measured on a real generated CV, where an
    enrolled applicant's master's rendered as "Sep 2024 - present" -- on a
    document whose whole purpose is applying while enrolled, and the reader
    could not tell when he finishes. The renderer prints a future end_date
    happily; nothing ever put one there.
    """
    enrolled = {k: v for k, v in _DEGREE.items() if k != "end_date"}
    make_fact(student, VerifiedFact.Category.EDUCATION, {**enrolled, "start_date": "2024-09-01"})

    questions = [q for q in incomplete_entry(student) if q.payload_key == "end_date"]

    assert len(questions) == 1
    assert "BSc Petroleum Engineering" in questions[0].evidence
    assert "expect" in questions[0].prompt.lower()


def test_a_finished_degree_is_not_asked_when_it_ends(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {**_DEGREE, "start_date": "2020-09-01", "end_date": "2024-06-30"},
    )

    assert [q for q in incomplete_entry(student) if q.payload_key == "end_date"] == []


def test_a_degree_that_already_states_its_grade_is_not_a_question(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {**_DEGREE, "grade_native": "16.45", "grade_scale": "20.0"},
    )

    assert missing_grade(student) == ()


def test_the_question_asks_for_the_mark_and_the_scale_together(student):
    """S-027: the grade goes on the institution's own scale, mark and
    denominator together. Asking for a bare number invites a conversion, and a
    conversion is a new claim nobody made.
    """
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))

    prompt = missing_grade(student)[0].prompt
    assert "scale" in prompt.lower()


def test_a_superseded_degree_is_not_asked_about(student):
    old = make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    new = make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {**_DEGREE, "grade_native": "16.45", "grade_scale": "20.0"},
    )
    new.supersedes = old
    new.save(update_fields=["supersedes"])

    assert missing_grade(student) == ()


def test_the_most_recent_degree_is_asked_for_its_thesis(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc Chemical Engineering",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
            "grade_native": "88/100",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc Chemoinformatics",
            "institution_original": "University of Strasbourg",
            "start_date": "2023-09-01",
        },
    )

    theses = [q for q in missing_degree_detail(student) if q.payload_key == "thesis_title"]

    assert len(theses) == 1
    assert "MSc Chemoinformatics" in theses[0].prompt


def test_a_degree_with_a_thesis_is_asked_who_supervised_it(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc Chemoinformatics",
            "institution_original": "University of Strasbourg",
            "start_date": "2023-09-01",
            "thesis_title": "Hierarchical GTM for reaction space",
        },
    )

    questions = missing_degree_detail(student)

    assert [q.payload_key for q in questions if q.payload_key == "supervisor"] == [
        "supervisor"
    ]
    assert not [q for q in questions if q.payload_key == "thesis_title"]


def test_a_completed_graded_degree_is_asked_for_a_rank(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc Chemical Engineering",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
            "grade_native": "88/100",
        },
    )

    assert "class_rank" in [q.payload_key for q in missing_degree_detail(student)]


def test_an_in_progress_degree_is_not_asked_for_a_rank(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc Chemoinformatics",
            "institution_original": "University of Strasbourg",
            "start_date": "2023-09-01",
            "grade_native": "15.8/20.0 to date",
        },
    )

    assert "class_rank" not in [q.payload_key for q in missing_degree_detail(student)]


def test_a_degree_with_no_grade_is_not_asked_for_a_rank(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )

    assert "class_rank" not in [q.payload_key for q in missing_degree_detail(student)]


def test_the_highest_completed_degree_is_asked_its_medium_of_instruction(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc Chemical Engineering",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )

    questions = missing_medium_of_instruction(student)

    assert [q.payload_key for q in questions] == ["medium_of_instruction"]
    assert "waive" not in questions[0].prompt.lower()
    assert "exempt" not in questions[0].prompt.lower()


def test_an_in_progress_degree_is_not_asked_its_medium_of_instruction(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc Chemoinformatics",
            "institution_original": "University of Strasbourg",
            "start_date": "2023-09-01",
        },
    )

    assert missing_medium_of_instruction(student) == ()


def test_a_degree_that_states_its_medium_is_not_asked_again(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
            "medium_of_instruction": "English",
        },
    )

    assert missing_medium_of_instruction(student) == ()


def test_a_language_with_no_test_score_is_asked_for_one(student):
    make_fact(
        student,
        VerifiedFact.Category.LANGUAGE,
        {"language": "English", "cefr_level": "C1"},
    )

    questions = missing_language_detail(student)

    assert [q.payload_key for q in questions] == ["test_score"]
    assert "IELTS" in questions[0].prompt


def test_a_mother_tongue_is_not_asked_for_a_test_score(student):
    make_fact(
        student,
        VerifiedFact.Category.LANGUAGE,
        {"language": "Azerbaijani", "cefr_level": "C2", "mother_tongue": True},
    )

    assert missing_language_detail(student) == ()


def test_a_language_with_no_level_is_asked_for_one(student):
    make_fact(
        student,
        VerifiedFact.Category.LANGUAGE,
        {"language": "French", "test_name": "DELF", "test_score": "B2"},
    )

    questions = missing_language_detail(student)

    assert [q.payload_key for q in questions] == ["cefr_level"]
    assert "French" in questions[0].prompt


def test_the_test_score_is_asked_before_the_level(student):
    make_fact(student, VerifiedFact.Category.LANGUAGE, {"language": "German"})

    assert [q.payload_key for q in missing_language_detail(student)] == [
        "test_score",
        "cefr_level",
    ]


_POST = {
    "employer": "EPFL",
    "title": "Research Assistant",
    "start_date": "2023-01-01",
    "end_date": "2024-06-30",
}
_PAPER = {"title": "A paper", "year": 2024}


def test_a_research_applicant_is_asked_who_supervised_a_post(student):
    """S-028, and the field most often lost: a CV prints
    "EPFL | Prof. Schwaller's group" on one line and the extractor folds it
    into the employer.
    """
    make_fact(student, VerifiedFact.Category.EXPERIENCE, dict(_POST))
    make_fact(student, VerifiedFact.Category.PUBLICATION, dict(_PAPER))

    assert "supervisor" in {q.payload_key for q in incomplete_entry(student)}


def test_an_applicant_with_no_research_record_is_not_asked_for_a_supervisor(student):
    """D2: the signal is the applicant's own ledger, not a keyword list over
    employer strings. A list would have to recognise CNRS, Max-Planck-Institut
    and Institut Curie, and would still miss the next one.
    """
    make_fact(student, VerifiedFact.Category.EXPERIENCE, dict(_POST))

    assert "supervisor" not in {q.payload_key for q in incomplete_entry(student)}


def test_a_post_that_already_names_its_supervisor_is_not_asked_about(student):
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {**_POST, "supervisor": "Prof. Schwaller"},
    )
    make_fact(student, VerifiedFact.Category.PUBLICATION, dict(_PAPER))

    assert "supervisor" not in {q.payload_key for q in incomplete_entry(student)}


def test_an_open_ended_post_is_asked_whether_it_is_still_running(student):
    """The doc asks for "no end_date and no present". In this schema
    end_date=None IS present -- every template renders it with
    |month_year:"present" -- so that state cannot exist. The real ambiguity is
    whether the CV meant "ongoing" or simply omitted the date.
    """
    make_fact(student, VerifiedFact.Category.EXPERIENCE, {**_POST, "end_date": None})

    questions = [q for q in incomplete_entry(student) if q.payload_key == "end_date"]
    assert len(questions) == 1
    assert "EPFL" in questions[0].evidence


def test_a_research_entry_with_no_institution_is_a_question(student):
    make_fact(
        student,
        VerifiedFact.Category.RESEARCH,
        {"thesis_title": "A thesis", "start_date": "2023-01-01"},
    )

    assert "institution" in {q.payload_key for q in incomplete_entry(student)}


def test_a_complete_record_produces_no_questions(student):
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {**_POST, "supervisor": "Prof. Schwaller"},
    )

    assert incomplete_entry(student) == ()


def test_an_answer_supersedes_the_fact_it_was_asked_about(student):
    fact = make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    question = missing_grade(student)[0]

    (written,) = answer_questions([(question, "16.45/20.0")], student=student)

    assert written.supersedes_id == fact.id
    assert written.payload["grade_native"] == "16.45/20.0"
    assert written.payload["degree_as_awarded"] == "BSc Petroleum Engineering"
    assert list(unsuperseded_facts(student).filter(category="EDUCATION")) == [written]


def test_two_answers_about_one_fact_write_one_row(student):
    """A post missing both its supervisor and its end date produces one
    question of each, on the same fact. Written one at a time, the first
    answer would supersede the fact the second names and the second would be
    refused as stale -- so they are written together, as one row.
    """
    make_fact(student, VerifiedFact.Category.EXPERIENCE, {**_POST, "end_date": None})
    make_fact(student, VerifiedFact.Category.PUBLICATION, dict(_PAPER))
    questions = [
        q for q in incomplete_entry(student) if q.payload_key in {"supervisor", "end_date"}
    ]
    assert len(questions) == 2

    written = answer_questions(
        [(questions[0], "Prof. Schwaller"), (questions[1], "2025-01-31")], student=student
    )

    assert len(written) == 1
    assert written[0].payload["supervisor"] == "Prof. Schwaller"
    assert written[0].payload["end_date"] == "2025-01-31"


def test_an_answer_is_a_candidate_and_never_a_confirmed_fact(student):
    """An answer is a student statement. The counsellor confirms; generation
    reads generatable_facts, which is unsuperseded AND confirmed, so nothing
    written here can reach a document on its own.
    """
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    question = missing_grade(student)[0]

    (written,) = answer_questions([(question, "16.45/20.0")], student=student)

    assert written.confirmed_by is None
    assert written.confirmed_at is None
    assert written.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT


def test_a_skipped_question_writes_nothing(student):
    """Every question is skippable -- a required answer to an inferred gap is a
    wall in front of a paying student. A blank is a skip, not an empty fact,
    and a form of blanks must not write a row.
    """
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    question = missing_grade(student)[0]

    assert answer_questions([(question, "   ")], student=student) == ()
    assert unsuperseded_facts(student).count() == 1


def test_an_answer_cannot_overwrite_an_authoritative_fact(student):
    """A DOI-fetched publication is AUTHORITATIVE_DOCUMENT. No type-3/4/5
    question targets one today, and this is why that stays true: a typed
    sentence must never quietly replace a registry's record.
    """
    fact = make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        dict(_PAPER),
        tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
    )
    question = GapQuestion(
        kind=Kind.INCOMPLETE_ENTRY,
        fact_id=fact.id,
        payload_key="venue",
        prompt="Where was it published?",
        evidence="no venue",
    )

    with pytest.raises(UnanswerableQuestion):
        answer_questions([(question, "Journal of Things")], student=student)


def test_an_answer_cannot_invent_a_payload_key(student):
    """payload_key arrives from a form. A key the category does not carry would
    put a value somewhere no reader looks and no verdict compares.
    """
    fact = make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    question = GapQuestion(
        kind=Kind.MISSING_GRADE,
        fact_id=fact.id,
        payload_key="salary",
        prompt="?",
        evidence="?",
    )

    with pytest.raises(UnanswerableQuestion):
        answer_questions([(question, "lots")], student=student)


def test_answering_another_student_s_question_is_refused(student, agency_a, django_user_model):
    """fact_id arrives from a form. It is a trust boundary, not a hint."""
    fact = make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    question = missing_grade(student)[0]
    other_user = django_user_model.objects.create(username="other-student")
    other = Membership.objects.create(
        tenant=agency_a, user=other_user, role=Membership.Role.STUDENT, active=True
    )

    with pytest.raises(UnanswerableQuestion):
        answer_questions([(question, "16.45/20.0")], student=other)

    assert VerifiedFact.objects.filter(supersedes=fact).count() == 0


def test_a_rejected_answer_writes_none_of_the_batch(student):
    """One form, one transaction. A student who answered three questions and
    tripped a guard on the fourth must not find two of them landed.

    The two questions must name DIFFERENT facts. Pointed at the same one they
    merge into a single update, the guard fires before anything is written,
    and the test passes with @transaction.atomic removed -- proving only that
    the guard works, which another test already does.
    """
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    other = make_fact(student, VerifiedFact.Category.EXPERIENCE, dict(_POST))
    good = missing_grade(student)[0]
    bad = GapQuestion(
        kind=Kind.INCOMPLETE_ENTRY,
        fact_id=other.id,
        payload_key="salary",
        prompt="?",
        evidence="?",
    )

    with pytest.raises(UnanswerableQuestion):
        answer_questions([(good, "16.45/20.0"), (bad, "lots")], student=student)

    assert VerifiedFact.objects.filter(source_ref="gap-interview").count() == 0


def test_the_cheapest_questions_come_first(student):
    """MISSING_CONTACT is cheapest to detect and cheapest to answer, so it
    should never be the reason a CV is weak. First in the form also means the
    student's first question is one they can answer without thinking.
    """
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    make_fact(student, VerifiedFact.Category.EXPERIENCE, {**_POST, "end_date": None})

    # MISSING_AWARD is last: it is the only one asking about something that is
    # not on the CV at all, so it is the most thought to answer.
    # MISSING_DEGREE_DETAIL (the thesis question for _DEGREE, the only and
    # therefore most recent EDUCATION fact, which has no thesis_title) fires
    # here too, right after MISSING_GRADE -- Task 4's own placement.
    # MEDIUM_OF_INSTRUCTION fires too -- _DEGREE is complete and states no
    # medium -- immediately after MISSING_LANGUAGE (which does not fire here:
    # no LANGUAGE fact exists) and before MISSING_GRADE, Task 5's placement.
    # ABSENT_SECTION fires last of all -- Task 8's own placement, after
    # MISSING_AWARD and before the (absent, here) programme block. It fires
    # unconditionally once the ledger is non-empty (the voluntary-work
    # question), and this fixture has no RESEARCH/PUBLICATION fact so the
    # referee question does not join it.
    # EDUCATION_COMPLETENESS fires last of all -- Task 9's own placement,
    # after ABSENT_SECTION. It too fires unconditionally on a non-empty
    # ledger (none of its three groups has been answered here).
    order = [
        Kind.MISSING_CONTACT,
        Kind.MEDIUM_OF_INSTRUCTION,
        Kind.MISSING_GRADE,
        Kind.MISSING_DEGREE_DETAIL,
        Kind.INCOMPLETE_ENTRY,
        Kind.MISSING_AWARD,
        Kind.ABSENT_SECTION,
        Kind.EDUCATION_COMPLETENESS,
    ]
    ranks = [order.index(q.kind) for q in gap_questions(student)]

    assert ranks == sorted(ranks)
    assert set(ranks) == {0, 1, 2, 3, 4, 5, 6, 7}


def test_an_empty_ledger_produces_no_questions(student):
    """Nothing has been uploaded. A form full of questions about a CV that does
    not exist is noise, not a gap.
    """
    assert gap_questions(student) == ()


def test_every_question_gap_questions_emits_can_be_answered(student):
    """The contract between the two halves of this module: anything
    gap_questions emits, answer_questions accepts. A question whose key its own
    category does not carry would be a dead end the student cannot clear, and
    this is the test that would have caught the same-fact batching bug.
    """
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    make_fact(student, VerifiedFact.Category.EXPERIENCE, {**_POST, "end_date": None})
    make_fact(student, VerifiedFact.Category.RESEARCH, {"thesis_title": "A thesis"})
    questions = gap_questions(student)
    assert questions

    written = answer_questions([(q, "an answer") for q in questions], student=student)

    # Grouped by (fact_id or slug), not by fact_id alone: Task 8 adds a second
    # and third create-path group (voluntary-role, referee) that, like
    # merit-award, carry fact_id=None. A plain {q.fact_id for q in questions}
    # collapses all three onto one "None" and undercounts writes -- each
    # distinct slug is still its own row.
    assert len(written) == len({q.fact_id or q.slug for q in questions})


def _programme_asking(program_factory, target, sentence="State your ECTS credits."):
    return program_factory(cv_directives=[{
        "action": "include", "target": target, "value": None,
        "rule_text": sentence, "source_url": "https://official.example/msc",
    }])


def test_a_field_the_programme_requires_and_the_ledger_lacks_is_a_question(
    student, program_factory
):
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    programme = _programme_asking(program_factory, "education.ects_credits")

    [q] = programme_required(student, programme)

    assert q.kind == Kind.PROGRAMME_REQUIRED and q.payload_key == "ects_credits"
    assert "State your ECTS credits." in q.evidence
    assert "BSc Petroleum Engineering" in q.prompt


def test_a_field_the_ledger_already_carries_is_not_asked_for(student, program_factory):
    make_fact(student, VerifiedFact.Category.EDUCATION, {**_DEGREE, "ects_credits": 180})
    programme = _programme_asking(program_factory, "education.ects_credits")
    assert programme_required(student, programme) == ()


def test_a_target_whose_key_the_category_does_not_carry_is_skipped(student, program_factory):
    """answer_questions refuses a key the category lacks; asking it would be
    a question nobody can answer.

    `personal.date_of_birth` is a real _INCLUDE_TARGETS entry the IDENTITY
    category does not carry -- the case this actually guards. It used to name
    `education.not_a_field`, which PageDirective now rejects on read, so the
    skip could never have been reached by a stored row.
    """
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    programme = program_factory(cv_directives=[{
        "action": "include", "target": "personal.date_of_birth", "value": None,
        "rule_text": "x", "source_url": "",
    }])
    assert programme_required(student, programme) == ()


def test_gap_questions_include_the_programmes_questions_when_one_is_given(student, program_factory):
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    programme = _programme_asking(program_factory, "education.ects_credits")
    kinds = [q.kind for q in gap_questions(student, programme=programme)]
    assert Kind.PROGRAMME_REQUIRED in kinds
    assert Kind.PROGRAMME_REQUIRED not in [q.kind for q in gap_questions(student)]


def test_a_programme_requiring_a_location_per_post_asks_for_the_missing_one(
    student, program_factory
):
    """R-061 (Europubhealth+, BINDING): "per experience, city + country".
    Ingestion may not supply a location the document never stated, so a post
    whose CV named only the employer reaches render with no city -- and before
    experience.city was a directive target, nothing asked the student for it.
    """
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {"employer": "EPFL", "title": "Research Intern", "bullets": ["Benchmarked frameworks."]},
    )
    programme = _programme_asking(program_factory, "experience.city")

    [question] = programme_required(student, programme)

    assert question.kind == Kind.PROGRAMME_REQUIRED and question.payload_key == "city"
    assert "Research Intern" in question.prompt


def test_a_publication_with_no_identifier_is_asked_for_one(student):
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {
            "title": "Hierarchical GTM for reaction space",
            "authors": ["Abdullayev, O.", "Schwaller, P."],
            "self_author_index": 0,
            "year": 2025,
        },
    )

    questions = missing_publication_detail(student)

    assert [q.payload_key for q in questions] == ["doi"]
    assert "landing page" in questions[0].prompt


def test_a_publication_with_a_url_is_not_asked_for_a_doi(student):
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {
            "title": "An IAC proceedings paper",
            "authors": ["Abdullayev, O."],
            "self_author_index": 0,
            "year": 2023,
            "url": "https://dl.iafastro.directory/event/IAC-2023/paper/76798/",
        },
    )

    assert missing_publication_detail(student) == ()


def test_a_publication_with_no_self_author_index_asks_which_position(student):
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {
            "title": "A paper",
            "authors": ["Roe, R.", "Abdullayev, O."],
            "doi": "10.1000/abcd",
            "year": 2024,
        },
    )

    questions = missing_publication_detail(student)

    assert [q.payload_key for q in questions] == ["self_author_index"]
    assert "Roe, R." in questions[0].evidence


def test_a_publication_with_no_year_is_asked_for_one(student):
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {
            "title": "A paper",
            "authors": ["Abdullayev, O."],
            "self_author_index": 0,
            "doi": "10.1000/abcd",
        },
    )

    assert [q.payload_key for q in missing_publication_detail(student)] == ["year"]


def test_a_student_with_no_priced_award_is_asked_about_scholarships_and_fee_waivers(student):
    """Owner observation 2026-09-15: applicants leave a scholarship or a 10%
    merit fee reduction off the CV because it reads to them as a fee
    arrangement rather than an honour. It is a competitive selection someone
    else made about them, which is what the reader is looking for."""
    # awarding_body is set so the per-award half of missing_award does not
    # also fire a MISSING_AWARD question here -- this test is about the
    # create-path question alone.
    make_fact(
        student,
        VerifiedFact.Category.AWARD,
        {"title": "2nd place at a hackathon", "awarding_body": "Hack the Valley"},
    )

    [question] = [q for q in gap_questions(student) if q.kind == Kind.MISSING_AWARD]

    assert question.fact_id is None, "an unmentioned award is a new fact, not a correction"
    assert question.category == VerifiedFact.Category.AWARD
    assert "fee reduction" in question.prompt
    assert "1 award(s), none with an amount or terms" in question.evidence


def test_an_award_that_already_states_its_terms_ends_the_question(student):
    """S-035's `detail` is where "IRCSS funded fees and EUR 12,000 stipend"
    lives, so an award carrying one has already answered this."""
    # awarding_body is set so the per-award half of missing_award does not
    # also fire a MISSING_AWARD question here -- this test is about the
    # create-path question alone.
    make_fact(
        student,
        VerifiedFact.Category.AWARD,
        {
            "title": "Foundation Fellowship",
            "detail": "EUR 9,102 stipend",
            "awarding_body": "The Foundation",
        },
    )
    assert not [q for q in gap_questions(student) if q.kind == Kind.MISSING_AWARD]


def test_answering_the_award_question_creates_a_fact_rather_than_superseding_one(student):
    # awarding_body is set so the per-award half of missing_award does not
    # also fire a second MISSING_AWARD question here -- this test is about
    # the create-path question alone.
    make_fact(
        student,
        VerifiedFact.Category.AWARD,
        {"title": "2nd place at a hackathon", "awarding_body": "Hack the Valley"},
    )
    [question] = [q for q in gap_questions(student) if q.kind == Kind.MISSING_AWARD]

    answer = "10% tuition reduction for academic merit"
    [written] = answer_questions([(question, answer)], student=student)

    assert written.category == VerifiedFact.Category.AWARD
    assert written.payload == {"title": "10% tuition reduction for academic merit"}
    assert written.supersedes_id is None
    # A candidate, like every other answer: a counsellor still gates it.
    assert written.confirmed_by_id is None
    assert {f.payload["title"] for f in unsuperseded_facts(student)} >= {
        "10% tuition reduction for academic merit",
        "2nd place at a hackathon",
    }


def test_an_award_with_no_awarding_body_is_asked_who_gave_it(student):
    make_fact(
        student,
        VerifiedFact.Category.AWARD,
        {"title": "Dean's Honour List", "date": "2022-06-01"},
    )

    questions = [q for q in missing_award(student) if q.payload_key == "awarding_body"]

    assert [q.payload_key for q in questions] == ["awarding_body"]
    assert "Dean's Honour List" in questions[0].prompt


def test_an_award_that_names_its_body_is_not_asked(student):
    make_fact(
        student,
        VerifiedFact.Category.AWARD,
        {"title": "Dean's Honour List", "awarding_body": "ADA University"},
    )

    assert [q for q in missing_award(student) if q.payload_key == "awarding_body"] == []


def test_a_created_answer_is_refused_a_key_its_category_does_not_carry(student):
    """Same trust boundary as the supersession path: the key is checked against
    the category, not trusted from the question object.

    The unknown-key guard only runs once a group is COMPLETE, so reaching it
    needs a question whose declared group keys themselves name an unsupported
    key -- a detector misconfiguration, not a value a form could produce.
    """
    bad = GapQuestion(
        kind=Kind.MISSING_AWARD,
        fact_id=None,
        category=VerifiedFact.Category.AWARD,
        payload_key="employer",
        prompt="x",
        evidence="y",
        slug="bad-group",
        group_keys=("employer",),
    )
    with pytest.raises(UnanswerableQuestion):
        answer_questions([(bad, "something")], student=student)


def test_an_in_progress_degree_is_asked_for_its_grade_so_far_not_its_final_grade(student):
    """Owner correction 2026-09-16: a fourth-year applicant has no final mark,
    and the real CV's in-progress MSc was being asked "what grade did you
    finish with". Cambridge's worked sample prints the form that IS a fact --
    "Second Year, 2.1 expected"."""
    enrolled = {k: v for k, v in _DEGREE.items() if k != "end_date"}
    make_fact(student, VerifiedFact.Category.EDUCATION, {**enrolled, "start_date": "2024-09-01"})
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {**_DEGREE, "degree_as_awarded": "MSc Future", "end_date": "2099-06-30"},
    )

    prompts = {q.evidence.split(" at ")[0]: q.prompt for q in missing_grade(student)}

    assert "grade so far" in prompts["BSc Petroleum Engineering"]
    assert "finish" not in prompts["BSc Petroleum Engineering"]
    assert "grade so far" in prompts["MSc Future"], "a future end date is still in progress"


def test_a_finished_degree_is_still_asked_for_its_final_grade(student):
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))

    [question] = missing_grade(student)

    assert "finish" in question.prompt
    assert "grade so far" not in question.prompt


def test_a_create_question_without_a_slug_is_a_programming_error():
    with pytest.raises(ValueError):
        GapQuestion(
            kind=Kind.MISSING_AWARD,
            fact_id=None,
            payload_key="title",
            prompt="?",
            evidence="?",
            category=VerifiedFact.Category.AWARD,
        )


def test_two_create_questions_sharing_a_slug_write_one_fact(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    group = [
        GapQuestion(
            kind=Kind.MISSING_AWARD,
            fact_id=None,
            payload_key=key,
            prompt="?",
            evidence="?",
            category=VerifiedFact.Category.EDUCATION,
            slug="exchange-programme",
            group_keys=("institution_original", "degree_as_awarded"),
        )
        for key in ("institution_original", "degree_as_awarded")
    ]

    written = answer_questions(
        [(group[0], "TU Delft"), (group[1], "Erasmus exchange semester")], student=student
    )

    assert len(written) == 1
    assert written[0].payload == {
        "institution_original": "TU Delft",
        "degree_as_awarded": "Erasmus exchange semester",
    }


def test_a_half_answered_create_group_writes_nothing(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    group = [
        GapQuestion(
            kind=Kind.MISSING_AWARD,
            fact_id=None,
            payload_key=key,
            prompt="?",
            evidence="?",
            category=VerifiedFact.Category.EDUCATION,
            slug="exchange-programme",
            group_keys=("institution_original", "degree_as_awarded"),
        )
        for key in ("institution_original", "degree_as_awarded")
    ]

    assert answer_questions([(group[0], "TU Delft"), (group[1], "")], student=student) == ()
    assert not unsuperseded_facts(student).filter(
        category=VerifiedFact.Category.EDUCATION
    ).exists()


def test_a_four_month_gap_between_two_entries_is_a_question(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc Chemical Engineering",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Research Intern",
            "start_date": "2023-11-01",
            "end_date": "2024-02-29",
        },
    )

    questions = timeline_gaps(student)

    # Plus the trailing span from the last entry to today.
    assert [q.slug for q in questions] == [
        "timeline-gap:2023-06-30:2023-11-01",
        "timeline-gap:2024-02-29:present",
    ]
    question = questions[0]
    assert question.kind == Kind.TIMELINE_GAP
    assert question.category == VerifiedFact.Category.TIMELINE
    assert question.fact_id is None
    assert question.payload_key == "statement"
    assert question.group_keys == ("statement",)
    assert question.defaults == (
        ("end_date", "2023-11-01"),
        ("start_date", "2023-06-30"),
    )
    assert "2023" in question.prompt


def test_a_two_month_gap_is_not_a_question(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Research Intern",
            "start_date": "2023-08-15",
            "end_date": "2024-02-29",
        },
    )

    assert [q.slug for q in timeline_gaps(student)] == ["timeline-gap:2024-02-29:present"]


def test_overlapping_entries_leave_no_gap(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc",
            "institution_original": "Strasbourg",
            "start_date": "2023-09-01",
            "end_date": "2025-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "EPFL",
            "title": "Intern",
            "start_date": "2024-02-01",
            "end_date": "2024-08-31",
        },
    )

    assert [q.slug for q in timeline_gaps(student)] == ["timeline-gap:2025-06-30:present"]


def test_an_entry_still_running_ends_the_timeline_today(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc",
            "institution_original": "Strasbourg",
            "start_date": "2023-09-01",
        },
    )

    assert timeline_gaps(student) == ()


def test_gap_notes_is_the_certificates_note_alone(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Intern",
            "start_date": "2023-11-01",
            "end_date": "2024-02-29",
        },
    )

    assert gap_notes(student) == (_CERTIFICATES_NOTE,)
    assert timeline_gaps(student)


def test_answering_a_timeline_gap_closes_it(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Intern",
            "start_date": "2023-11-01",
            "end_date": "2024-02-29",
        },
    )
    question = next(
        q for q in timeline_gaps(student) if q.slug == "timeline-gap:2023-06-30:2023-11-01"
    )

    written = answer_questions(
        [(question, "Full-time carer for a family member.")], student=student
    )

    assert len(written) == 1
    assert written[0].payload == {
        "start_date": "2023-06-30",
        "end_date": "2023-11-01",
        "statement": "Full-time carer for a family member.",
    }
    assert written[0].source_ref == "gap-interview:timeline-gap:2023-06-30:2023-11-01"
    assert not [q for q in timeline_gaps(student) if q.slug == "timeline-gap:2023-06-30:2023-11-01"]


def test_a_span_from_the_last_entry_to_today_is_asked(student):
    """ETH: "all details right up to the time of application"."""
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )

    questions = timeline_gaps(student)

    assert len(questions) == 1
    assert questions[0].slug == "timeline-gap:2023-06-30:present"
    # No end date: the span runs to today, and today moves.
    assert questions[0].defaults == (("start_date", "2023-06-30"),)


def test_answering_the_trailing_gap_closes_it_permanently(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    question = timeline_gaps(student)[0]

    written = answer_questions([(question, "Full-time job-hunting.")], student=student)

    assert written[0].payload == {
        "start_date": "2023-06-30",
        "statement": "Full-time job-hunting.",
    }
    # An entry with no end date covers the timeline to today, forever -- so
    # this does not reopen in 93 days the way an end_date of today would.
    assert timeline_gaps(student) == ()


def test_an_entry_running_to_today_leaves_no_trailing_gap(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc",
            "institution_original": "Strasbourg",
            "start_date": "2023-09-01",
        },
    )

    assert timeline_gaps(student) == ()


def test_two_gaps_get_two_distinct_form_fields(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2016-09-01",
            "end_date": "2019-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Intern",
            "start_date": "2020-06-01",
            "end_date": "2020-12-31",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "EPFL",
            "title": "Intern",
            "start_date": "2022-01-01",
            "end_date": "2022-08-31",
        },
    )

    questions = timeline_gaps(student)

    # Two between-entry gaps plus the trailing one to today.
    assert len(questions) == 3
    assert len({field_name(q) for q in questions}) == 3


def test_a_widened_gap_asks_only_the_remainder(student):
    """An answer covers the span it was asked about. When a neighbouring
    entry's dates are later corrected, the new hole is asked under its own
    slug and the old answer still stands."""
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.TIMELINE,
        {
            "start_date": "2023-06-30",
            "end_date": "2023-11-01",
            "statement": "Full-time carer for a family member.",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Intern",
            "start_date": "2024-03-01",
            "end_date": "2024-08-31",
        },
    )

    slugs = {q.slug for q in timeline_gaps(student)}

    assert "timeline-gap:2023-11-01:2024-03-01" in slugs
    assert not any(slug.startswith("timeline-gap:2023-06-30") for slug in slugs)


def test_an_open_gap_statement_stops_at_the_next_post(student):
    """A trailing-gap answer has no end date. Once a later post is on file it
    ends where that post starts -- read as "to today" forever, it would hide
    every gap after the post."""
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.TIMELINE,
        {"start_date": "2023-06-30", "statement": "Full-time job-hunting."},
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Intern",
            "start_date": "2024-03-01",
            "end_date": "2024-06-30",
        },
    )

    assert [q.slug for q in timeline_gaps(student)] == ["timeline-gap:2024-06-30:present"]


def test_an_entry_that_has_not_started_yet_covers_nothing(student):
    """A place starting next year must not turn the months before it into a
    gap that ends in the future."""
    today = date.today()
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": f"{today.year - 4}-09-01",
            "end_date": f"{today.year - 1}-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc",
            "institution_original": "TUM",
            "start_date": f"{today.year + 1}-10-01",
            "end_date": f"{today.year + 3}-09-30",
        },
    )

    slugs = [q.slug for q in timeline_gaps(student)]

    # Asked as the span to today, not as a span ending in the future.
    assert slugs == [f"timeline-gap:{today.year - 1}-06-30:present"]


def test_an_answer_longer_than_the_entry_allows_is_refused(student):
    """The ledger keeps any string, so the cap is enforced where the answer
    arrives -- otherwise every later generation fails."""
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    question = timeline_gaps(student)[0]

    with pytest.raises(UnanswerableQuestion):
        answer_questions(
            [(question, "x" * (TIMELINE_STATEMENT_MAX + 1))], student=student
        )
    assert not unsuperseded_facts(student).filter(
        category=VerifiedFact.Category.TIMELINE
    ).exists()


def test_a_timeline_answer_is_stored_as_the_entry_tidies_it(student):
    """The answer goes through TimelineEntry on the way in, so the ledger holds
    what generation will print -- and the CV entry built from it verifies."""
    from apps.documents.schemas import (
        CVContent,
        EducationEntry,
        PersonalInformation,
        TimelineEntry,
    )
    from apps.documents.verification import Verdict, verify_against_facts

    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    question = timeline_gaps(student)[0]

    (fact,) = answer_questions([(question, "Carer ( family )")], student=student)

    assert fact.payload == {"start_date": "2023-06-30", "statement": "Carer (family)"}
    fact.confirmed_by = student
    content = CVContent(
        personal_information=PersonalInformation(
            full_name="A Student", email="student@example.com"
        ),
        education=(EducationEntry(degree_as_awarded="BSc", institution_original="ADA"),),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
        timeline=(TimelineEntry.model_validate(fact.payload),),
    )
    verdicts = [
        v for v in verify_against_facts(content, [fact]) if v.claim_path.startswith("timeline")
    ]
    assert [v.verdict for v in verdicts] == [Verdict.SUPPORTED]


def test_voluntary_work_is_asked_unconditionally(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})

    questions = absent_sections(student)
    voluntary = [q for q in questions if q.slug == "voluntary-role"]

    assert {q.payload_key for q in voluntary} == {"employer", "title", "bullets"}
    assert all(q.category == VerifiedFact.Category.EXPERIENCE for q in voluntary)


def test_an_empty_ledger_is_asked_nothing(student):
    assert absent_sections(student) == ()
    assert gap_notes(student) == ()


def test_a_research_applicant_with_no_referee_is_asked_for_one(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {"title": "A paper", "authors": ["Abdullayev, O."], "self_author_index": 0},
    )

    referees = [q for q in absent_sections(student) if q.slug == "referee"]

    assert [q.payload_key for q in referees] == ["name"]


def test_a_student_who_already_named_a_referee_is_not_asked(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {"title": "A paper", "authors": ["Abdullayev, O."], "self_author_index": 0},
    )
    make_fact(student, VerifiedFact.Category.REFERENCE, {"name": "Prof. Someone"})

    assert [q for q in absent_sections(student) if q.slug == "referee"] == []


def test_certificates_are_a_note_and_never_a_question(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})

    notes = gap_notes(student)

    assert len(notes) == 1
    assert "certificate" in notes[0].text.lower()
    assert not any("certificate" in q.prompt.lower() for q in gap_questions(student))


def test_a_voluntary_role_answered_in_full_becomes_one_experience_fact(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q for q in absent_sections(student) if q.slug == "voluntary-role"
    }

    written = answer_questions(
        [
            (by_key["employer"], "Azerbaijani Chemistry Society"),
            (by_key["title"], "Volunteer tutor"),
            (by_key["bullets"], "Taught weekly chemistry classes to 20 school students."),
        ],
        student=student,
    )

    assert len(written) == 1
    assert written[0].category == VerifiedFact.Category.EXPERIENCE
    assert written[0].payload["title"] == "Volunteer tutor"


def test_a_created_bullets_answer_lands_as_a_list_like_every_other_experience_fact(student):
    """verification.fact_payload builds `bullets` from ExperienceEntry.bullets,
    a tuple, so every ingested EXPERIENCE fact carries it as a list.
    generation._facts_payload puts both shapes in front of the model under one
    key, so a typed answer stored as a bare string is a real defect, not a
    style choice. `title` is a plain string field and must stay untouched."""
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q for q in absent_sections(student) if q.slug == "voluntary-role"
    }

    [written] = answer_questions(
        [
            (by_key["employer"], "Azerbaijani Chemistry Society"),
            (by_key["title"], "Volunteer tutor"),
            (by_key["bullets"], "Taught weekly chemistry classes to 20 school students."),
        ],
        student=student,
    )

    assert written.payload["bullets"] == [
        "Taught weekly chemistry classes to 20 school students."
    ]
    assert written.payload["title"] == "Volunteer tutor"


def test_a_created_facts_source_ref_carries_its_slug(student):
    """The stamp _already_created reads back. A created fact is otherwise a
    plain EXPERIENCE row -- an employer, a title, a bullet, same as a job --
    so this prefix is the only thing that can say "this group was already
    answered" (see gaps.py's module docstring on the old ``unpaid`` guard).
    """
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q for q in absent_sections(student) if q.slug == "voluntary-role"
    }

    [written] = answer_questions(
        [
            (by_key["employer"], "Azerbaijani Chemistry Society"),
            (by_key["title"], "Volunteer tutor"),
            (by_key["bullets"], "Taught weekly chemistry classes to 20 school students."),
        ],
        student=student,
    )

    assert written.source_ref == "gap-interview:voluntary-role"


def test_a_superseding_answers_source_ref_stays_bare(student):
    """The update/supersede path is untouched by the slug stamp: it never
    needs _already_created, because a superseded fact already carries the
    field it corrects."""
    make_fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    question = missing_grade(student)[0]

    (written,) = answer_questions([(question, "16.45/20.0")], student=student)

    assert written.source_ref == "gap-interview"


def test_a_fully_answered_voluntary_role_stops_asking(student):
    """The regression this task exists to fix: the old guard checked an
    ``unpaid`` payload key that no fact in this ledger has ever carried
    (it is not in _PAYLOAD_KEYS[EXPERIENCE]), so it re-fired on every page
    load forever, even after the student answered."""
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q for q in absent_sections(student) if q.slug == "voluntary-role"
    }

    answer_questions(
        [
            (by_key["employer"], "Azerbaijani Chemistry Society"),
            (by_key["title"], "Volunteer tutor"),
            (by_key["bullets"], "Taught weekly chemistry classes to 20 school students."),
        ],
        student=student,
    )

    assert [q for q in absent_sections(student) if q.slug == "voluntary-role"] == []


def test_a_fully_answered_voluntary_role_carries_unpaid_true(student):
    """The student said so by answering "have you done any voluntary,
    community or society work?" -- asking a second question would be asking
    twice, and leaving it unset would file the role as paid employment in
    the one place that splits on it (funder_templates/rhodes.py, R-080)."""
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q for q in absent_sections(student) if q.slug == "voluntary-role"
    }

    [written] = answer_questions(
        [
            (by_key["employer"], "Azerbaijani Chemistry Society"),
            (by_key["title"], "Volunteer tutor"),
            (by_key["bullets"], "Taught weekly chemistry classes to 20 school students."),
        ],
        student=student,
    )

    assert written.payload["unpaid"] is True


def test_a_society_role_carries_no_unpaid_key(student):
    """society-role is NOT in _GROUP_DEFAULTS: a paid student-union officer
    exists, so the group's answer does not settle the flag by construction."""
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q for q in education_completeness(student) if q.slug == "society-role"
    }

    [written] = answer_questions(
        [
            (by_key["employer"], "Student Union"),
            (by_key["title"], "Treasurer"),
            (by_key["bullets"], "Managed the society's annual budget."),
        ],
        student=student,
    )

    assert "unpaid" not in written.payload


def test_a_half_answered_voluntary_role_writes_nothing(student):
    """The default must not make a partial group's all-or-nothing guard
    writeable: a default is not something the student answered, so it is
    merged in after the completeness check, never before it."""
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q for q in absent_sections(student) if q.slug == "voluntary-role"
    }

    written = answer_questions(
        [
            (by_key["employer"], "Azerbaijani Chemistry Society"),
            (by_key["title"], "Volunteer tutor"),
        ],
        student=student,
    )

    assert written == ()


def test_a_referee_answered_once_stops_asking(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {"title": "A paper", "authors": ["Abdullayev, O."], "self_author_index": 0},
    )
    [question] = [q for q in absent_sections(student) if q.slug == "referee"]

    answer_questions([(question, "Prof. Someone")], student=student)

    assert [q for q in absent_sections(student) if q.slug == "referee"] == []
    # The assertion above is guarded twice over -- `not _current(REFERENCE)`
    # alone already blocks re-asking forever once any referee fact exists,
    # because this ledger is append-only and a REFERENCE fact is never
    # superseded away. That makes it pass even with a broken
    # `_already_created`, which a negative-control probe (setting
    # `_already_created` to always return False) confirmed 2026-09-17:
    # every other "stops asking" test failed under that probe, this one
    # alone still passed. Assert the stamp `_already_created` actually reads
    # so a regression there is caught here too.
    assert gaps._already_created(student, "referee")


def test_an_exchange_and_an_unfinished_programme_are_both_asked(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})

    slugs = {q.slug for q in education_completeness(student)}

    assert slugs == {"exchange-programme", "unfinished-programme", "society-role"}


def test_each_education_group_asks_for_an_institution_and_a_degree(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})

    for slug in ("exchange-programme", "unfinished-programme"):
        keys = {q.payload_key for q in education_completeness(student) if q.slug == slug}
        assert keys == {"institution_original", "degree_as_awarded"}


def test_education_completeness_asks_an_empty_ledger_nothing(student):
    assert education_completeness(student) == ()


def test_an_exchange_answered_in_full_becomes_one_education_fact(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q
        for q in education_completeness(student)
        if q.slug == "exchange-programme"
    }

    written = answer_questions(
        [
            (by_key["institution_original"], "TU Delft"),
            (by_key["degree_as_awarded"], "Erasmus exchange semester, Applied Chemistry"),
        ],
        student=student,
    )

    assert len(written) == 1
    assert written[0].category == VerifiedFact.Category.EDUCATION


def test_every_create_group_asks_exactly_its_declared_keys(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {"title": "A paper", "authors": ["Abdullayev, O."], "self_author_index": 0},
    )

    creates = [q for q in gap_questions(student) if q.fact_id is None]

    assert creates
    for slug in {q.slug for q in creates}:
        group = [q for q in creates if q.slug == slug]
        # One declaration per group, and the group asks exactly what it declares:
        # a key declared and never asked would make the group unwritable, a key
        # asked and not declared would be silently dropped.
        assert len({q.group_keys for q in group}) == 1
        assert {q.payload_key for q in group} == set(group[0].group_keys)


def test_an_exchange_answered_in_full_stops_asking(student):
    """Amendment to Task 9: education_completeness gates each of its three
    groups on _already_created, same mechanism as voluntary-role and
    referee -- otherwise a create-path question is indistinguishable from an
    ordinary fact once answered and re-fires forever."""
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q
        for q in education_completeness(student)
        if q.slug == "exchange-programme"
    }

    answer_questions(
        [
            (by_key["institution_original"], "TU Delft"),
            (by_key["degree_as_awarded"], "Erasmus exchange semester, Applied Chemistry"),
        ],
        student=student,
    )

    assert [q for q in education_completeness(student) if q.slug == "exchange-programme"] == []


def test_an_unfinished_programme_answered_in_full_stops_asking(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q
        for q in education_completeness(student)
        if q.slug == "unfinished-programme"
    }

    answer_questions(
        [
            (by_key["institution_original"], "EPFL"),
            (by_key["degree_as_awarded"], "BSc Physics (not completed)"),
        ],
        student=student,
    )

    assert [
        q for q in education_completeness(student) if q.slug == "unfinished-programme"
    ] == []


def test_a_society_role_answered_in_full_stops_asking(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q for q in education_completeness(student) if q.slug == "society-role"
    }

    answer_questions(
        [
            (by_key["employer"], "Student Union"),
            (by_key["title"], "Treasurer"),
            (by_key["bullets"], "Managed the society's annual budget."),
        ],
        student=student,
    )

    assert [q for q in education_completeness(student) if q.slug == "society-role"] == []


def test_the_interview_asks_the_real_cv_more_than_the_old_four_checks_did(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc Chemoinformatics",
            "institution_original": "University of Strasbourg",
            "start_date": "2023-09-01",
        },
    )
    make_fact(student, VerifiedFact.Category.LANGUAGE, {"language": "English"})

    kinds = {q.kind for q in gap_questions(student)}

    assert kinds >= {
        Kind.MISSING_CONTACT,
        Kind.MISSING_LANGUAGE,
        Kind.MISSING_GRADE,
        Kind.MISSING_DEGREE_DETAIL,
        Kind.ABSENT_SECTION,
        Kind.EDUCATION_COMPLETENESS,
    }


def test_the_language_certificate_is_asked_before_a_publication_year(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(student, VerifiedFact.Category.LANGUAGE, {"language": "English"})
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {
            "title": "A paper",
            "authors": ["Abdullayev, O."],
            "self_author_index": 0,
            "doi": "10.1000/abcd",
        },
    )

    keys = [q.payload_key for q in gap_questions(student)]

    assert keys.index("test_score") < keys.index("year")


def test_a_timeline_fact_can_be_stored(student):
    fact = make_fact(
        student,
        VerifiedFact.Category.TIMELINE,
        {
            "start_date": "2023-06-30",
            "end_date": "2023-11-01",
            "statement": "Full-time carer for a family member.",
        },
    )

    assert fact.category == "TIMELINE"
    assert unsuperseded_facts(student).filter(
        category=VerifiedFact.Category.TIMELINE
    ).count() == 1


def test_a_create_question_declares_its_own_group_keys_and_defaults(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {"degree_as_awarded": "MSc", "institution_original": "Strasbourg"},
    )

    voluntary = [q for q in gap_questions(student) if q.slug == "voluntary-role"]

    assert {q.group_keys for q in voluntary} == {("employer", "title", "bullets")}
    assert {q.defaults for q in voluntary} == {(("unpaid", True),)}


def test_a_question_with_no_fact_and_no_group_keys_is_refused():
    with pytest.raises(ValueError):
        GapQuestion(
            kind=Kind.ABSENT_SECTION,
            fact_id=None,
            slug="anything",
            payload_key="title",
            prompt="?",
            evidence="?",
            category=VerifiedFact.Category.AWARD,
        )


def test_a_refused_gap_answer_carries_no_cause_holding_the_students_words(student, monkeypatch):
    """A pydantic ValidationError carries the rejected input, and a gap answer is
    health or family data more often than not. Chained with `from error` it would
    reach any log that records __cause__ (approval.py makes the same choice for
    the same reason). Unreachable from a real form today -- the length guard runs
    first and the dates are the server's -- so the double forces a real
    ValidationError whose input is the student's sentence."""
    from apps.documents.schemas import TimelineEntry

    original = TimelineEntry.model_validate

    def _rejects(data):
        return original({**data, "unexpected": data["statement"]})

    monkeypatch.setattr(gaps.TimelineEntry, "model_validate", staticmethod(_rejects))
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {"degree_as_awarded": "BSc", "institution_original": "ADA University",
         "start_date": "2019-09-01", "end_date": "2023-06-30"},
    )
    question = timeline_gaps(student)[0]

    with pytest.raises(UnanswerableQuestion) as caught:
        answer_questions([(question, "Treated for depression.")], student=student)

    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    assert "depression" not in str(caught.value)
