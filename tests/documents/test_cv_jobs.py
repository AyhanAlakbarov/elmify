"""Per-application CV job queueing, waiting states, and resume (CV build step 4.2)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.documents import cv_jobs, document_worker
from apps.documents.confirmation import confirm_facts
from apps.documents.document_queue import DocumentWorkMessage
from apps.documents.generation import (
    ApplicationEmailMissing,
    GenerationResult,
    IdentityNotConfirmed,
)
from apps.documents.models import DocumentDraft, VerifiedFact
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.portals import packets, prepare
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


class _CapturedQueue(list[DocumentWorkMessage]):
    def __init__(self) -> None:
        super().__init__()
        self.delays: list[int] = []


@pytest.fixture
def captured_queue(monkeypatch) -> _CapturedQueue:
    sent = _CapturedQueue()

    def _enqueue(message: DocumentWorkMessage, **kwargs: object) -> None:
        sent.append(message)
        delay = kwargs.get("delay_seconds", 0)
        sent.delays.append(int(delay) if isinstance(delay, int) else 0)

    monkeypatch.setattr(cv_jobs, "enqueue_document_work", _enqueue)
    monkeypatch.setattr(cv_jobs.transaction, "on_commit", lambda fn: fn())
    return sent


def _content() -> CVContent:
    return CVContent(
        personal_information=PersonalInformation(
            full_name="Jane Doe", email="jane@example.com"
        ),
        education=(
            EducationEntry(
                degree_as_awarded="BSc",
                institution_original="Example U",
                city="Berlin",
                country="DE",
                start_date="2020-09-01",
            ),
        ),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )


def _programme_card(
    agency,
    student,
    program_factory,
    *,
    identity_confirmed: bool = True,
    application_email: str = "jane@example.com",
    cv_status: str = "",
    cv_format_requirement: str = "any",
) -> Application:
    programme = program_factory(cv_format_requirement=cv_format_requirement)
    with tenant_scope(agency.id):
        Membership.objects.filter(id=student.id).update(
            application_email=application_email
        )
        student.application_email = application_email
        if identity_confirmed and not VerifiedFact.objects.filter(
            student=student,
            category=VerifiedFact.Category.IDENTITY,
            confirmed_by__isnull=False,
        ).exists():
            VerifiedFact.objects.create(
                student=student,
                category=VerifiedFact.Category.IDENTITY,
                payload={"full_name": "Jane Doe"},
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref="upload:test",
                confirmed_by=student,
                confirmed_at=timezone.now(),
                created_by=student,
            )
        return Application.objects.create(
            tenant=agency,
            student=student,
            program_id=programme.id,
            cv_status=cv_status,
        )


def _generate_message(card: Application) -> DocumentWorkMessage:
    return DocumentWorkMessage(
        action="generate",
        kind=DocumentDraft.Kind.CV,
        tenant_id=card.tenant_id,
        student_id=card.student_id,
        application_id=card.id,
        programme_id=card.program_id,
    )


def _run_capture(card: Application, monkeypatch) -> None:
    monkeypatch.setattr(packets, "capture_requirements", lambda _app: None)
    monkeypatch.setattr(prepare, "prepare_documents", lambda _app, **_kw: [])
    document_worker._capture(
        DocumentWorkMessage(
            action="capture_requirements",
            kind="KIT",
            tenant_id=card.tenant_id,
            student_id=card.student_id,
            application_id=card.id,
        )
    )


def _run_generate(*, application: Application, monkeypatch) -> None:
    def _fake_generate(*, student, programme, requirements=None, opportunity=None):
        if not VerifiedFact.objects.filter(
            student=student,
            category=VerifiedFact.Category.IDENTITY,
            confirmed_by__isnull=False,
        ).exists():
            raise IdentityNotConfirmed("identity not confirmed")
        if not student.application_email:
            raise ApplicationEmailMissing("application email missing")
        return GenerationResult(content=_content(), verdicts=(), retried=False)

    monkeypatch.setattr(document_worker, "generate_cv", _fake_generate)
    document_worker._generate(_generate_message(application))


def _identity_fact(student: Membership) -> VerifiedFact:
    with tenant_scope(student.tenant_id):
        return VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Jane Doe"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            confirmed_by=None,
            created_by=student,
        )


def test_capture_queues_the_applications_cv(
    agency_a, membership_a, program_factory, captured_queue, monkeypatch
) -> None:
    card = _programme_card(agency_a, membership_a, program_factory)
    _run_capture(card, monkeypatch)
    assert [(m.action, m.application_id) for m in captured_queue] == [
        ("generate", card.id)
    ]
    with tenant_scope(agency_a.id):
        card.refresh_from_db()
    assert card.cv_status == "QUEUED"


def test_capture_twice_queues_one_cv(
    agency_a, membership_a, program_factory, captured_queue, monkeypatch
) -> None:
    card = _programme_card(agency_a, membership_a, program_factory)
    _run_capture(card, monkeypatch)
    _run_capture(card, monkeypatch)
    assert sum(m.action == "generate" for m in captured_queue) == 1


def test_missing_identity_becomes_a_waiting_state_not_a_dead_letter(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    card = _programme_card(
        agency_a, membership_a, program_factory, identity_confirmed=False
    )
    _run_generate(application=card, monkeypatch=monkeypatch)
    with tenant_scope(agency_a.id):
        card.refresh_from_db()
    assert card.cv_status == "WAITING_IDENTITY"


def test_missing_email_becomes_a_waiting_state(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    card = _programme_card(
        agency_a, membership_a, program_factory, application_email=""
    )
    _run_generate(application=card, monkeypatch=monkeypatch)
    with tenant_scope(agency_a.id):
        card.refresh_from_db()
    assert card.cv_status == "WAITING_EMAIL"


def test_confirming_identity_resumes_every_waiting_cv(
    agency_a, membership_a, program_factory, captured_queue
) -> None:
    a = _programme_card(
        agency_a,
        membership_a,
        program_factory,
        identity_confirmed=False,
        cv_status="WAITING_IDENTITY",
    )
    b = _programme_card(
        agency_a,
        membership_a,
        program_factory,
        identity_confirmed=False,
        cv_status="WAITING_IDENTITY",
    )
    fact = _identity_fact(a.student)
    with tenant_scope(agency_a.id):
        confirm_facts(student=a.student, fact_ids=[fact.id], actor=a.student)
    assert {m.application_id for m in captured_queue} == {a.id, b.id}


def test_a_use_our_form_programme_gets_no_cv(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    card = _programme_card(
        agency_a,
        membership_a,
        program_factory,
        cv_format_requirement="structured_fields_only",
    )
    _run_generate(application=card, monkeypatch=monkeypatch)
    with tenant_scope(agency_a.id):
        card.refresh_from_db()
        assert (
            card.cv_status == "NO_CV"
            and not DocumentDraft.objects.filter(application=card).exists()
        )


def test_a_job_for_a_removed_application_is_dropped(
    agency_a, membership_a, program_factory
) -> None:
    card = _programme_card(agency_a, membership_a, program_factory)
    message = _generate_message(card)
    with tenant_scope(agency_a.id):
        card.delete()
    document_worker._generate(message)
    with tenant_scope(agency_a.id):
        assert not DocumentDraft.objects.exists()


def _fill_bucket(bucket: str, student: Membership, count: int) -> None:
    from apps.ratelimit import rate_limited

    for _ in range(count):
        rate_limited(bucket, student.id, limit=count, window_seconds=3600)


def _run_generate_with_real_limiter(
    *, application: Application, monkeypatch
) -> None:
    from types import SimpleNamespace

    from apps.documents import generation

    monkeypatch.setattr(generation, "OpenAI", lambda: SimpleNamespace(responses=None))
    monkeypatch.setattr(generation, "_call_model", lambda *_a, **_kw: _content())
    document_worker._generate(_generate_message(application))


def test_a_cv_limit_defers_the_job_instead_of_raising(
    agency_a, membership_a, program_factory, captured_queue, monkeypatch
) -> None:
    card = _programme_card(agency_a, membership_a, program_factory)
    _fill_bucket("cv_generation", membership_a, 10)
    _run_generate_with_real_limiter(application=card, monkeypatch=monkeypatch)
    assert (
        captured_queue[-1].application_id == card.id
        and captured_queue.delays[-1] == 900
    )
    with tenant_scope(agency_a.id):
        card.refresh_from_db()
    assert card.cv_status == "QUEUED" and card.cv_resumes_at is not None


def test_a_skill_match_limit_defers_the_job_too(
    agency_a, membership_a, program_factory, captured_queue, monkeypatch
) -> None:
    from apps.documents import generation
    from apps.documents.tailoring import SkillMatchRateLimited

    card = _programme_card(agency_a, membership_a, program_factory)
    monkeypatch.setattr(
        generation,
        "_tailor",
        lambda *_a, **_kw: (_ for _ in ()).throw(SkillMatchRateLimited("limited")),
    )
    _run_generate_with_real_limiter(application=card, monkeypatch=monkeypatch)
    assert captured_queue[-1].application_id == card.id


def test_a_still_limited_job_defers_again(
    agency_a, membership_a, program_factory, captured_queue, monkeypatch
) -> None:
    card = _programme_card(agency_a, membership_a, program_factory)
    _fill_bucket("cv_generation", membership_a, 10)
    _run_generate_with_real_limiter(application=card, monkeypatch=monkeypatch)
    _run_generate_with_real_limiter(application=card, monkeypatch=monkeypatch)
    assert sum(m.application_id == card.id for m in captured_queue) == 2


def test_a_failed_defer_leaves_the_message_for_redelivery(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    card = _programme_card(agency_a, membership_a, program_factory)
    monkeypatch.setattr(
        cv_jobs,
        "enqueue_document_work",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("sqs down")),
    )
    _fill_bucket("cv_generation", membership_a, 10)
    with pytest.raises(RuntimeError):
        _run_generate_with_real_limiter(application=card, monkeypatch=monkeypatch)
