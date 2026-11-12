"""The scan handler's decisions, not GuardDuty's and not the extractor's.

ingest_uploaded_cv is monkeypatched throughout: what is under test here is
which events cause an ingestion at all, and extraction has its own module.
"""

import pytest
from django.conf import settings

from apps.concierge.documents import register
from apps.documents import document_worker
from apps.documents.document_queue import DocumentWorkMessage, ScanResultEvent
from apps.documents.drafts import create_draft
from apps.documents.generation import GenerationResult
from apps.documents.ingestion import UnsupportedUpload
from apps.documents.models import DocumentDraft, VerifiedFact
from apps.documents.render import RenderedArtifact, UnsupportedRenderVariant
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.tenancy.context import tenant_scope

from .conftest import make_identity_fact

pytestmark = pytest.mark.django_db


@pytest.fixture
def ingested(monkeypatch):
    """Records every ingest_uploaded_cv call instead of making one."""
    calls = []
    monkeypatch.setattr(
        document_worker,
        "ingest_uploaded_cv",
        lambda **kwargs: calls.append(kwargs) or (),
    )
    return calls


def _event(document, status="NO_THREATS_FOUND", bucket=None):
    return ScanResultEvent(
        object_key=document.object_key,
        scan_result=status,
        bucket_name=bucket or settings.EVIDENCE_BUCKET_NAME,
    )


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("NO_THREATS_FOUND", "AVAILABLE"),
        ("THREATS_FOUND", "BLOCKED"),
        ("UNSUPPORTED", "REVIEW_REQUIRED"),
        ("ACCESS_DENIED", "REVIEW_REQUIRED"),
        ("FAILED", "REVIEW_REQUIRED"),
    ],
)
def test_every_documented_status_reaches_its_state(
    agency_a, membership_a, ingested, status, state
):
    document = register(agency_a.id, membership_a.id)

    document_worker.handle_scan_result(_event(document, status))

    document.refresh_from_db()
    assert document.state == state


def test_only_a_clean_scan_triggers_ingestion(agency_a, membership_a, ingested):
    """An infected upload must reach neither the extractor nor the ledger."""
    blocked = register(agency_a.id, membership_a.id)
    clean = register(agency_a.id, membership_a.id)

    document_worker.handle_scan_result(_event(blocked, "THREATS_FOUND"))
    assert ingested == []

    document_worker.handle_scan_result(_event(clean, "NO_THREATS_FOUND"))
    assert [call["document"].id for call in ingested] == [clean.id]


def test_a_redelivered_message_does_not_ingest_twice(agency_a, membership_a, ingested):
    """SQS delivery is at-least-once. Without the guard a redelivery
    duplicates every candidate fact the upload produced, and the student
    confirms the same claim twice."""
    document = register(agency_a.id, membership_a.id)
    with tenant_scope(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Jane Doe"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref=f"upload:{document.id}",
            confirmed_by=None,
            created_by=membership_a,
        )

    document_worker.handle_scan_result(_event(document))

    assert ingested == []


def test_an_unknown_object_key_is_dropped_not_raised(agency_a, membership_a, ingested):
    """The message is deleted rather than redelivered forever: an event for a
    key we never minted is never going to find a row."""
    event = ScanResultEvent(
        object_key="quarantine/00000000-0000-0000-0000-0000000000a1/"
        "00000000-0000-0000-0000-0000000000b2",
        scan_result="NO_THREATS_FOUND",
        bucket_name=settings.EVIDENCE_BUCKET_NAME,
    )

    document_worker.handle_scan_result(event)

    assert ingested == []


def test_a_key_outside_the_quarantine_shape_is_dropped(agency_a, membership_a, ingested):
    """The object key is the ONLY thing trusted out of the event, so its shape
    is checked: nothing else in the envelope may choose which row is written."""
    event = ScanResultEvent(
        object_key="tenants/anything/else",
        scan_result="NO_THREATS_FOUND",
        bucket_name=settings.EVIDENCE_BUCKET_NAME,
    )

    document_worker.handle_scan_result(event)

    assert ingested == []


def test_an_event_for_another_bucket_is_ignored(agency_a, membership_a, ingested):
    """The EventBridge rule matches on detail-type and source, which are
    account-wide: a scan of some other bucket must not write our rows."""
    document = register(agency_a.id, membership_a.id)

    document_worker.handle_scan_result(_event(document, bucket="someone-elses-bucket"))

    document.refresh_from_db()
    assert document.state == "QUARANTINED"
    assert ingested == []


def test_an_unknown_status_lands_in_review_and_does_not_ingest(
    agency_a, membership_a, ingested
):
    """AWS may add a sixth scanResultStatus. Treating it as clean would ingest
    an unscanned file; crashing would wedge the queue."""
    document = register(agency_a.id, membership_a.id)

    document_worker.handle_scan_result(_event(document, "SOMETHING_NEW"))

    document.refresh_from_db()
    assert document.state == "REVIEW_REQUIRED"
    assert ingested == []


def test_an_unreadable_upload_is_terminal_visible_and_not_a_crash(
    agency_a, membership_a, monkeypatch
):
    """A JPEG, a PNG or a .txt CV -- the commonest user error there is.

    Uncaught, UnsupportedUpload escapes consume_once and the command's
    two-exception filter, so the ECS task dies and the traceback pages
    someone. Worse: the ingestion's transaction rolls back with it and the
    poll endpoint answers QUARANTINED forever --
    the exact indistinguishability upload_status was created to prevent. The
    scan verdict must SURVIVE, which is what refresh_from_db pins here.
    """

    def _unreadable(**_kwargs):
        raise UnsupportedUpload("upload is neither a PDF nor a DOCX")

    monkeypatch.setattr(document_worker, "ingest_uploaded_cv", _unreadable)
    document = register(agency_a.id, membership_a.id)

    document_worker.handle_scan_result(_event(document))

    document.refresh_from_db()
    assert document.state == "REVIEW_REQUIRED"
    assert document.scan_result == "NO_THREATS_FOUND"


def _content():
    return CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
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


def _approved_draft(agency_a, membership_a, variant=""):
    with tenant_scope(agency_a.id):
        draft = create_draft(
            student=membership_a,
            kind=DocumentDraft.Kind.CV,
            content=_content(),
            render_variant=variant,
        )
        DocumentDraft.objects.filter(id=draft.id).update(
            status=DocumentDraft.Status.APPROVED
        )
        draft.refresh_from_db()
    return draft


def test_a_generate_message_writes_a_draft(agency_a, membership_a, monkeypatch):
    monkeypatch.setattr(
        document_worker,
        "generate_cv",
        lambda **kwargs: GenerationResult(content=_content(), verdicts=(), retried=False),
    )
    with tenant_scope(agency_a.id):
        make_identity_fact(membership_a)

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="generate",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency_a.id,
            student_id=membership_a.id,
        )
    )

    with tenant_scope(agency_a.id):
        draft = DocumentDraft.objects.get(student=membership_a)
    assert draft.version == 1
    assert draft.status == DocumentDraft.Status.DRAFT


def test_a_generate_message_with_a_programme_tailors_and_records_it(
    agency_a, membership_a, monkeypatch, program_factory
):
    """Two halves, and the draft half is the one that is easy to miss: without
    a programme on the DRAFT, resolve_variant sees None and renders STANDARD,
    so a funder's curated cv_format_requirement never reaches the document."""
    programme = program_factory()
    seen = {}

    def _generate(**kwargs):
        seen.update(kwargs)
        return GenerationResult(content=_content(), verdicts=(), retried=False)

    monkeypatch.setattr(document_worker, "generate_cv", _generate)
    with tenant_scope(agency_a.id):
        make_identity_fact(membership_a)

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="generate",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency_a.id,
            student_id=membership_a.id,
            programme_id=programme.id,
        )
    )

    assert seen["programme"] == programme
    with tenant_scope(agency_a.id):
        draft = DocumentDraft.objects.get(student=membership_a)
    assert draft.programme_id == programme.id


def test_a_generate_message_naming_no_programme_is_dropped_not_crashed(
    agency_a, membership_a, monkeypatch, caplog
):
    """The door checks only UUID shape now, so this is the one place an
    unknown id is refused. Returning (not raising) is what gets the message
    deleted: raising would crash the task and redeliver it three times into
    the DLQ, and no redelivery makes an unknown id known."""
    from uuid import uuid4

    monkeypatch.setattr(
        document_worker, "generate_cv", lambda **kwargs: pytest.fail("generated anyway")
    )
    programme_id = uuid4()

    with caplog.at_level("WARNING", logger="apps.documents.document_worker"):
        document_worker.handle_document_work(
            DocumentWorkMessage(
                action="generate",
                kind=DocumentDraft.Kind.CV,
                tenant_id=agency_a.id,
                student_id=membership_a.id,
                programme_id=programme_id,
            )
        )

    assert "DocumentGenerateUnknownProgramme" in caplog.text
    assert str(programme_id) in caplog.text
    with tenant_scope(agency_a.id):
        assert not DocumentDraft.objects.filter(student=membership_a).exists()


def test_a_generate_message_without_a_programme_still_generates_untailored(
    agency_a, membership_a, monkeypatch
):
    seen = {}

    def _generate(**kwargs):
        seen.update(kwargs)
        return GenerationResult(content=_content(), verdicts=(), retried=False)

    monkeypatch.setattr(document_worker, "generate_cv", _generate)
    with tenant_scope(agency_a.id):
        make_identity_fact(membership_a)

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="generate",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency_a.id,
            student_id=membership_a.id,
        )
    )

    assert seen["programme"] is None
    with tenant_scope(agency_a.id):
        assert DocumentDraft.objects.get(student=membership_a).programme_id is None


def test_a_europass_api_render_is_handed_to_the_pinned_worker(
    agency_a, membership_a, monkeypatch
):
    """That queue is single-worker and pinned for the circuit breaker and the
    europa.eu courtesy rate. Rendering here would bypass both, and nothing
    would be storing the artefact either."""
    handed = []
    rendered = []
    monkeypatch.setattr(
        document_worker, "enqueue_europass_render", lambda message, **kw: handed.append(message)
    )
    monkeypatch.setattr(document_worker, "render_draft", lambda **kw: rendered.append(kw))
    draft = _approved_draft(agency_a, membership_a, variant="EUROPASS_API")

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="render",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency_a.id,
            student_id=membership_a.id,
            draft_id=draft.id,
        )
    )

    assert [message.draft_id for message in handed] == [draft.id]
    assert rendered == []


def test_a_local_variant_is_stored_under_the_drafts_own_key(
    agency_a, membership_a, monkeypatch, fake_store
):
    monkeypatch.setattr(
        document_worker,
        "render_draft",
        lambda **kw: RenderedArtifact(
            variant="STANDARD",
            pdf_bytes=b"%PDF-1.7",
            field_mapped=None,
            page_count=1,
            byte_size=8,
        ),
    )
    monkeypatch.setattr(document_worker, "_object_store", lambda: fake_store)
    draft = _approved_draft(agency_a, membership_a, variant="STANDARD")

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="render",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency_a.id,
            student_id=membership_a.id,
            draft_id=draft.id,
        )
    )

    key = (
        f"tenants/{agency_a.id}/students/{membership_a.id}"
        f"/documents/{draft.id}/cv-standard.pdf"
    )
    assert fake_store.get(key) == b"%PDF-1.7"


def test_a_variant_with_no_worker_render_path_fails_loudly(
    agency_a, membership_a, monkeypatch
):
    """FIELD_MAPPED produces a dict rather than bytes and FUNDER_TEMPLATE needs
    a funder_template_id no draft carries. Storing an empty artefact would be
    a silent wrong answer; a raise sends the message to the DLQ, where the
    alarm is."""
    draft = _approved_draft(agency_a, membership_a, variant="FIELD_MAPPED")

    with pytest.raises(UnsupportedRenderVariant):
        document_worker.handle_document_work(
            DocumentWorkMessage(
                action="render",
                kind=DocumentDraft.Kind.CV,
                tenant_id=agency_a.id,
                student_id=membership_a.id,
                draft_id=draft.id,
            )
        )


def test_a_generate_message_for_a_kind_this_worker_cannot_make_is_refused(
    agency_a, membership_a, monkeypatch
):
    """The module promises a dispatch on kind and _generate called generate_cv
    regardless, so widening api._SUPPORTED_KINDS alone would have filed a
    motivation letter as a CV -- create_draft stores whatever kind it is
    handed. Raising sends the message to the DLQ, where the alarm is."""
    monkeypatch.setattr(
        document_worker, "generate_cv", lambda **_kw: pytest.fail("generation ran")
    )

    with pytest.raises(ValueError):
        document_worker.handle_document_work(
            DocumentWorkMessage(
                action="generate",
                kind=DocumentDraft.Kind.MOTIVATION_LETTER,
                tenant_id=agency_a.id,
                student_id=membership_a.id,
            )
        )

    with tenant_scope(agency_a.id):
        assert not DocumentDraft.objects.filter(student=membership_a).exists()


def test_a_generate_message_for_a_blocked_programme_is_dropped(
    agency_a, membership_a, monkeypatch, caplog, program_factory
):
    from apps.funding.models import Program
    from tests.research.provenance_helpers import make_body, recognise

    programme = program_factory()
    Program.objects.filter(id=programme.id).update(
        evidence_domain="bircham.edu", evidence_institutional=True
    )
    recognise(make_body("bircham.edu"), "bircham.edu", "mill_list")
    monkeypatch.setattr(
        document_worker, "generate_cv", lambda **kwargs: pytest.fail("generated anyway")
    )
    with caplog.at_level("WARNING", logger="apps.documents.document_worker"):
        document_worker.handle_document_work(
            DocumentWorkMessage(
                action="generate", kind=DocumentDraft.Kind.CV, tenant_id=agency_a.id,
                student_id=membership_a.id, programme_id=programme.id,
            )
        )
    assert "DocumentGenerateBlockedProgramme" in caplog.text
    with tenant_scope(agency_a.id):
        assert not DocumentDraft.objects.filter(student=membership_a).exists()


def test_a_clean_passport_is_stored_and_never_read_as_a_cv(agency_a, membership_a, ingested):
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")

    document_worker.handle_scan_result(_event(document))

    document.refresh_from_db()
    assert document.state == "AVAILABLE"
    assert ingested == []


def test_capture_requirements_runs_in_the_worker(agency_a, membership_a, monkeypatch):
    from uuid import uuid4

    from apps.portals import packets
    from apps.portals.models import Application

    calls = []
    monkeypatch.setattr(
        packets, "capture_requirements", lambda application: calls.append(application.id)
    )
    with tenant_scope(agency_a.id):
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4()
        )

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="capture_requirements", kind="KIT", tenant_id=agency_a.id,
            student_id=membership_a.id, application_id=application.id,
        )
    )

    assert calls == [application.id]


def test_capture_for_a_removed_application_is_dropped(agency_a, membership_a, monkeypatch):
    """Removed between Add and the worker: no later delivery finds it, so no retry."""
    from uuid import uuid4

    from apps.portals import packets

    monkeypatch.setattr(
        packets, "capture_requirements", lambda application: pytest.fail("captured anyway")
    )
    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="capture_requirements", kind="KIT", tenant_id=agency_a.id,
            student_id=membership_a.id, application_id=uuid4(),
        )
    )


@pytest.fixture
def prepared(monkeypatch):
    """What the worker asked prepare_documents to prepare, by application id."""
    from apps.portals import prepare

    calls = []
    monkeypatch.setattr(
        prepare, "prepare_documents", lambda application, **_kw: calls.append(application.id)
    )
    return calls


def _open_and_withdrawn(agency, student):
    from uuid import uuid4

    from apps.portals.models import Application

    with tenant_scope(agency.id):
        open_ = Application.objects.create(tenant=agency, student=student, program_id=uuid4())
        Application.objects.create(
            tenant=agency, student=student, program_id=uuid4(), outcome="WITHDRAWN"
        )
    return open_


def test_a_prepare_message_prepares_each_open_application(agency_a, membership_a, prepared):
    open_ = _open_and_withdrawn(agency_a, membership_a)

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="prepare_documents", kind="PREPARE", tenant_id=agency_a.id,
            student_id=membership_a.id,
        )
    )

    assert prepared == [open_.id]


def test_a_preparation_that_fails_is_logged_never_raised(
    agency_a, membership_a, monkeypatch, caplog
):
    from apps.portals import prepare

    def _boom(application, **_kw):
        raise RuntimeError("bug")

    monkeypatch.setattr(prepare, "prepare_documents", _boom)
    _open_and_withdrawn(agency_a, membership_a)

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="prepare_documents", kind="PREPARE", tenant_id=agency_a.id,
            student_id=membership_a.id,
        )
    )

    assert "PrepareFailed" in caplog.text


def test_capture_prepares_the_application_after_the_copy(
    agency_a, membership_a, monkeypatch, prepared
):
    from uuid import uuid4

    from apps.portals import packets
    from apps.portals.models import Application

    order = []
    monkeypatch.setattr(
        packets, "capture_requirements", lambda application: order.append(("copy", prepared[:]))
    )
    with tenant_scope(agency_a.id):
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4()
        )

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="capture_requirements", kind="KIT", tenant_id=agency_a.id,
            student_id=membership_a.id, application_id=application.id,
        )
    )

    assert order == [("copy", [])] and prepared == [application.id]


def test_a_render_prepares_the_students_applications(
    agency_a, membership_a, monkeypatch, fake_store, prepared
):
    """Approval queues preparation, but the render it waits on may finish later:
    a CV is preparable only once rendered, so the render prepares too."""
    monkeypatch.setattr(
        document_worker,
        "render_draft",
        lambda **kw: RenderedArtifact(
            variant="STANDARD", pdf_bytes=b"%PDF-1.7", field_mapped=None, page_count=1,
            byte_size=8,
        ),
    )
    monkeypatch.setattr(document_worker, "_object_store", lambda: fake_store)
    draft = _approved_draft(agency_a, membership_a, variant="STANDARD")
    open_ = _open_and_withdrawn(agency_a, membership_a)

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="render", kind=DocumentDraft.Kind.CV, tenant_id=agency_a.id,
            student_id=membership_a.id, draft_id=draft.id,
        )
    )

    assert prepared == [open_.id]


def test_a_down_parser_stops_the_run_for_every_application(
    agency_a, membership_a, monkeypatch, caplog
):
    from uuid import uuid4

    from apps.documents.ocr_errors import OcrUnavailable
    from apps.portals import prepare
    from apps.portals.models import Application

    calls = []

    def _down(application, **_kw):
        calls.append(application.id)
        raise OcrUnavailable("down")

    monkeypatch.setattr(prepare, "prepare_documents", _down)
    with tenant_scope(agency_a.id):
        for _ in range(2):
            Application.objects.create(tenant=agency_a, student=membership_a, program_id=uuid4())

    document_worker._prepare(agency_a.id, membership_a.id)

    assert len(calls) == 1
    assert "PrepareFailed" not in caplog.text


def test_one_time_budget_covers_every_application_in_a_run(agency_a, membership_a, monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    from apps.portals import prepare
    from apps.portals.models import Application

    clock = [0.0]
    monkeypatch.setattr(document_worker, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls = []

    def _slow(application, *, budget, **_kw):
        calls.append(budget)
        clock[0] += 10  # the first application spends the run's budget
        return []

    monkeypatch.setattr(prepare, "prepare_documents", _slow)
    monkeypatch.setattr(prepare, "PREPARE_BUDGET_SECONDS", 5.0)
    with tenant_scope(agency_a.id):
        for _ in range(2):
            Application.objects.create(tenant=agency_a, student=membership_a, program_id=uuid4())

    document_worker._prepare(agency_a.id, membership_a.id)

    assert calls == [5.0]


@pytest.mark.parametrize(("elapsed", "budget"), [(820.0, None), (100.0, 240.0), (700.0, 110.0)])
def test_preparation_after_a_scan_fits_inside_the_scan_queues_visibility_timeout(
    agency_a, membership_a, monkeypatch, elapsed, budget
):
    """900 s visibility, 90 s for one parser call plus margin: what the scan's own
    work (a transcript read can take minutes) leaves, capped at 240 s, or nothing."""
    from types import SimpleNamespace

    clock = [0.0]
    monkeypatch.setattr(document_worker, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def _slow_ingest(**_kw):
        clock[0] += elapsed
        return ()

    monkeypatch.setattr(document_worker, "ingest_uploaded_cv", _slow_ingest)
    budgets = []
    monkeypatch.setattr(
        document_worker, "_prepare",
        lambda tenant_id, student_id, **kw: budgets.append(kw.get("budget")),
    )
    document = register(agency_a.id, membership_a.id, kind="CV")

    document_worker.handle_scan_result(_event(document))

    assert budgets == ([] if budget is None else [budget])


@pytest.fixture
def queued(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "apps.documents.document_queue.enqueue_document_work",
        lambda message, **kwargs: sent.append(message),
    )
    return sent


@pytest.mark.parametrize(
    "kind,queues", [("CV", True), ("THESIS_OR_REPORT", True), ("PASSPORT", False)]
)
def test_a_promoted_cv_or_thesis_queues_an_evidence_refresh(
    agency_a, membership_a, ingested, queued, django_capture_on_commit_callbacks, kind, queues
):
    document = register(agency_a.id, membership_a.id, kind=kind)

    with django_capture_on_commit_callbacks(execute=True):
        document_worker.handle_scan_result(_event(document))

    refreshes = [m.student_id for m in queued if m.action == "refresh_evidence"]
    assert refreshes == ([membership_a.id] if queues else [])


def test_the_refresh_job_runs_for_an_active_student_only(agency_a, membership_a, monkeypatch):
    from apps.tenancy.models import Membership

    calls = []
    monkeypatch.setattr(
        document_worker.evidence_refresh,
        "refresh_evidence",
        lambda student, **kwargs: calls.append(student.id),
    )
    message = DocumentWorkMessage(
        action="refresh_evidence",
        kind="EVIDENCE",
        tenant_id=agency_a.id,
        student_id=membership_a.id,
    )

    document_worker.handle_document_work(message)
    with tenant_scope(agency_a.id):
        Membership.objects.filter(id=membership_a.id).update(active=False)
    document_worker.handle_document_work(message)

    assert calls == [membership_a.id]


def test_final_3_the_refresh_job_never_runs_for_a_student_being_erased(
    agency_a, membership_a, monkeypatch
):
    from apps.audit.models import DeletionRequest

    calls = []
    monkeypatch.setattr(
        document_worker.evidence_refresh,
        "refresh_evidence",
        lambda student, **kwargs: calls.append(student.id),
    )
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(tenant=agency_a, student=membership_a, state="APPROVED")
    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="refresh_evidence",
            kind="EVIDENCE",
            tenant_id=agency_a.id,
            student_id=membership_a.id,
        )
    )
    assert calls == []


@pytest.mark.django_db(transaction=True)
def test_no_transaction_is_open_while_the_refresh_runs(agency_a, membership_a, monkeypatch):
    from django.db import connection

    seen = []
    monkeypatch.setattr(
        document_worker.evidence_refresh,
        "refresh_evidence",
        lambda student, **kwargs: seen.append(connection.in_atomic_block),
    )
    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="refresh_evidence",
            kind="EVIDENCE",
            tenant_id=agency_a.id,
            student_id=membership_a.id,
        )
    )
    assert seen == [False]


def test_funder_template_variant_renders_and_stores_when_opportunity_has_template(
    agency_a, membership_a, monkeypatch, fake_store
):
    from apps.documents.drafts import create_draft
    from apps.funding.models import FundingFamily, FundingOpportunity, OpportunityScope

    monkeypatch.setattr(document_worker, "_object_store", lambda: fake_store)
    sisgp = FundingOpportunity.objects.create(
        canonical_key="sisgp",
        name="Swedish Institute Scholarship for Global Professionals",
        family=FundingFamily.PRIVATE_FOUNDATION,
        scope_type=OpportunityScope.GLOBAL,
    )
    with tenant_scope(agency_a.id):
        draft = create_draft(
            student=membership_a,
            kind=DocumentDraft.Kind.CV,
            content=_content(),
            funding_opportunity=sisgp,
            render_variant="FUNDER_TEMPLATE",
        )
        DocumentDraft.objects.filter(id=draft.id).update(
            status=DocumentDraft.Status.APPROVED
        )

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="render",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency_a.id,
            student_id=membership_a.id,
            draft_id=draft.id,
        )
    )
    key = (
        f"tenants/{agency_a.id}/students/{membership_a.id}"
        f"/documents/{draft.id}/cv-funder-template.pdf"
    )
    assert fake_store.get(key).startswith(b"%PDF")


def test_a_generate_job_meeting_pending_changes_is_dropped(
    agency_a, membership_a, monkeypatch, caplog
):
    from apps.documents.generation import ChangesPending

    def _pending(**kwargs):
        raise ChangesPending("settle the changes from the newer CV first")

    monkeypatch.setattr(document_worker, "generate_cv", _pending)
    with tenant_scope(agency_a.id):
        make_identity_fact(membership_a)

    with caplog.at_level("WARNING", logger="apps.documents.document_worker"):
        document_worker.handle_document_work(
            DocumentWorkMessage(
                action="generate",
                kind=DocumentDraft.Kind.CV,
                tenant_id=agency_a.id,
                student_id=membership_a.id,
            )
        )

    assert "DocumentGenerateChangesPending" in caplog.text
    with tenant_scope(agency_a.id):
        assert not DocumentDraft.objects.filter(student=membership_a).exists()


def test_a_generate_message_stores_the_applied_fixes(agency_a, membership_a, monkeypatch):
    from apps.documents.cv_fixes import AppliedFix

    fix = AppliedFix("soft_skill", "e" * 64, "skills", "Teamwork", "")
    monkeypatch.setattr(
        document_worker,
        "generate_cv",
        lambda **kwargs: GenerationResult(
            content=_content(), verdicts=(), retried=False, applied_fixes=(fix,)
        ),
    )
    with tenant_scope(agency_a.id):
        make_identity_fact(membership_a)
    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="generate",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency_a.id,
            student_id=membership_a.id,
        )
    )
    with tenant_scope(agency_a.id):
        draft = DocumentDraft.objects.get(student=membership_a)
    assert draft.applied_fixes == [fix.as_json()]


def test_a_render_message_persists_the_artifacts_warnings_on_the_draft(
    agency_a, membership_a, monkeypatch, fake_store
):
    from apps.documents.constraints import ConstraintRule, Enforcement
    from apps.documents.drafts import create_draft
    from apps.documents.render import ConstraintViolation

    violation = ConstraintViolation(
        rule=ConstraintRule(
            rule_id="R-031",
            key="signature_required",
            value=True,
            enforcement=Enforcement.ADVISORY_HIGH_RISK,
            rule_text="Sign the last page.",
        ),
        detail="a signature is required",
    )
    monkeypatch.setattr(document_worker, "_object_store", lambda: fake_store)
    monkeypatch.setattr(
        document_worker,
        "render_draft",
        lambda **kwargs: RenderedArtifact(
            variant="STANDARD",
            pdf_bytes=b"%PDF-1.4\n",
            field_mapped=None,
            page_count=1,
            byte_size=9,
            warnings=(violation,),
        ),
    )
    with tenant_scope(agency_a.id):
        draft = create_draft(
            student=membership_a, kind=DocumentDraft.Kind.CV, content=_content()
        )
        DocumentDraft.objects.filter(id=draft.id).update(status=DocumentDraft.Status.APPROVED)

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="render",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency_a.id,
            student_id=membership_a.id,
            draft_id=draft.id,
        )
    )
    with tenant_scope(agency_a.id):
        draft.refresh_from_db()
    assert draft.render_warnings == [
        {
            "rule_id": "R-031",
            "key": "signature_required",
            "scope": "",
            "detail": "a signature is required",
            "source_url": "",
        }
    ]


def test_left_out_items_reach_the_drafts_change_list(agency_a, membership_a, monkeypatch):
    from apps.documents.selection import LeftOut

    left = LeftOut(section="awards", text="Old prize (2009)", digest="d" * 64,
                   reason="before the period the programme asks for")

    def _generate(**kwargs):
        return GenerationResult(content=_content(), verdicts=(), retried=False, left_out=(left,))

    monkeypatch.setattr(document_worker, "generate_cv", _generate)
    with tenant_scope(agency_a.id):
        make_identity_fact(membership_a)
    document_worker.handle_document_work(DocumentWorkMessage(
        action="generate", kind=DocumentDraft.Kind.CV, tenant_id=agency_a.id,
        student_id=membership_a.id,
    ))
    with tenant_scope(agency_a.id):
        draft = DocumentDraft.objects.get(student=membership_a)
    assert {"kind": "left_out", "section": "awards", "item": "Old prize (2009)",
            "item_digest": "d" * 64,
            "reason": "before the period the programme asks for"} in draft.applied_fixes



