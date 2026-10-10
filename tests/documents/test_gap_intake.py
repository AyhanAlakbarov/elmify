import pytest

from apps.documents.gap_intake import field_name, submit_answers
from apps.documents.gaps import (
    GapQuestion,
    Kind,
    UnanswerableQuestion,
    gap_questions,
    timeline_gaps,
)
from apps.documents.models import VerifiedFact
from apps.documents.verification import unsuperseded_facts
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

from .conftest import make_fact

pytestmark = pytest.mark.django_db


@pytest.fixture
def student(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="intake-student")
        yield Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )


def _degree_without_a_grade(student):
    return make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {"degree_as_awarded": "MSc Chemistry", "institution_original": "EPFL"},
    )


def test_an_answer_keyed_by_its_field_name_is_written(student):
    degree = _degree_without_a_grade(student)

    written = submit_answers({f"{degree.id}:grade_native": "16.45/20.0"}, student=student)

    assert [fact.payload["grade_native"] for fact in written] == ["16.45/20.0"]
    assert written[0].supersedes_id == degree.id


def test_a_payload_key_no_question_asked_about_is_ignored(student):
    """The whole point of re-deriving the questions.

    EDUCATION carries grade_conversion, so answer_questions would accept it --
    payload_keys() is category-wide. No detector asks for it, and gaps.py says
    in as many words that a conversion is a claim nobody made. A submission
    naming it must therefore reach nothing.
    """
    degree = _degree_without_a_grade(student)

    written = submit_answers({f"{degree.id}:grade_conversion": "3.9/4.0"}, student=student)

    assert written == ()
    assert unsuperseded_facts(student).get(id=degree.id).payload.get("grade_conversion") is None


def test_a_field_name_for_a_superseded_fact_is_ignored(student):
    """The ledger can move between the render and the submit -- a second tab, a
    counsellor edit, a double submit. A name for a fact that is no longer the
    tip of its chain matches no re-derived question and is dropped, rather than
    landing on whatever took its place.
    """
    degree = _degree_without_a_grade(student)
    submit_answers({f"{degree.id}:grade_native": "16.45/20.0"}, student=student)

    written = submit_answers({f"{degree.id}:grade_native": "18.0/20.0"}, student=student)

    assert written == ()


def test_another_student_s_fact_id_is_ignored(student, agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        other_user = django_user_model.objects.create(username="intake-other")
        other = Membership.objects.create(
            tenant=agency_a, user=other_user, role=Membership.Role.STUDENT, active=True
        )
    their_degree = _degree_without_a_grade(other)
    _degree_without_a_grade(student)

    written = submit_answers({f"{their_degree.id}:grade_native": "20.0/20.0"}, student=student)

    assert written == ()
    assert unsuperseded_facts(other).get(id=their_degree.id).payload.get("grade_native") is None


def test_a_blank_answer_writes_nothing(student):
    """Every question is skippable, and a form of blanks is an ordinary
    outcome rather than an error.
    """
    degree = _degree_without_a_grade(student)

    assert submit_answers({f"{degree.id}:grade_native": "   "}, student=student) == ()


def test_a_submission_with_no_recognised_key_at_all_writes_nothing(student):
    """A CSRF token and a submit button are in every real submission."""
    _degree_without_a_grade(student)

    written = submit_answers({"csrfmiddlewaretoken": "abc123", "submit": "Save"}, student=student)

    assert written == ()


def test_every_question_can_be_named_and_answered(student):
    """field_name is the contract, so building a submission out of it must
    reach every question gap_questions emits -- not most of them.
    """
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    _degree_without_a_grade(student)
    make_fact(student, VerifiedFact.Category.RESEARCH, {"thesis_title": "A thesis"})

    questions = gap_questions(student)
    written = submit_answers(
        {field_name(question): "an answer" for question in questions}, student=student
    )

    answered = {(fact.supersedes_id, key) for fact in written for key in fact.payload}
    assert {(q.fact_id, q.payload_key) for q in questions} <= answered


def test_each_written_fact_is_audited_to_the_student(student):
    degree = _degree_without_a_grade(student)

    written = submit_answers({f"{degree.id}:grade_native": "16.45/20.0"}, student=student)

    events = AuditEvent.objects.filter(event="document.gap_answered")
    assert [event.object_id for event in events] == [written[0].id]
    assert events.get().actor_id == student.id
    assert events.get().actor_kind == AuditEvent.ActorKind.HUMAN


def test_a_counsellor_operated_submit_names_the_counsellor(student, agency_a, django_user_model):
    """created_by on the fact is provenance and stays the student; the audit
    trail is where the operator is recorded. Same split as drafts.py.
    """
    with tenant_scope(agency_a.id):
        counsellor_user = django_user_model.objects.create(username="intake-counsellor")
        counsellor = Membership.objects.create(
            tenant=agency_a, user=counsellor_user, role=Membership.Role.COUNSELOR, active=True
        )
    degree = _degree_without_a_grade(student)

    written = submit_answers(
        {f"{degree.id}:grade_native": "16.45/20.0"}, student=student, actor=counsellor
    )

    assert written[0].created_by_id == student.id
    assert AuditEvent.objects.get(event="document.gap_answered").actor_id == counsellor.id


def test_a_skipped_form_audits_nothing(student):
    _degree_without_a_grade(student)

    submit_answers({}, student=student)

    assert not AuditEvent.objects.filter(event="document.gap_answered").exists()


def test_a_refused_batch_writes_neither_fact_nor_event(student):
    """An authoritative fact cannot be answered over. Nothing writes an
    authoritative EDUCATION fact today, so this is unreachable through the
    current detectors -- it becomes reachable the day transcript ingestion
    lands, and a half-written batch is not how anyone should find out.
    """
    degree = make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {"degree_as_awarded": "MSc Chemistry"},
        tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
    )

    with pytest.raises(UnanswerableQuestion):
        submit_answers({f"{degree.id}:grade_native": "16.45/20.0"}, student=student)

    assert unsuperseded_facts(student).count() == 1
    assert not AuditEvent.objects.filter(event="document.gap_answered").exists()


def test_two_create_questions_with_the_same_key_get_different_field_names():
    def question(slug):
        return GapQuestion(
            kind=Kind.MISSING_AWARD,
            fact_id=None,
            payload_key="title",
            prompt="?",
            evidence="?",
            category=VerifiedFact.Category.AWARD,
            slug=slug,
            group_keys=("title",),
        )

    assert field_name(question("merit-award")) != field_name(question("voluntary-role"))


def test_a_timeline_answer_round_trips_through_the_form(student):
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

    written = submit_answers(
        {field_name(question): "Full-time carer for a family member."}, student=student
    )

    assert len(written) == 1
    assert written[0].category == VerifiedFact.Category.TIMELINE
    assert not [
        q for q in timeline_gaps(student) if q.slug == "timeline-gap:2023-06-30:2023-11-01"
    ]
