"""Spec 2026-10-12 §5.1, §6.1, §6.4: the worker path for a passport."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.concierge.documents import register, upload_prefix
from apps.concierge.models import DocumentVersion
from apps.documents import document_reading
from apps.documents.document_reading import MAX_ATTEMPTS
from apps.documents.models import DocumentReading, VerifiedFact
from apps.documents.ocr_errors import OcrUnavailable
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.documents.id_fixtures import passport

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _on(settings):
    settings.FACT_READING_ENABLED = True
    settings.TRANSCRIPT_AZURE_ENABLED = True


class _Store:
    def __init__(self, body=b"%PDF-1.7 passport"):
        self.body = body

    def get(self, key):
        return self.body


def _passport_upload(agency, student):
    # ADD: these tests hold several passports at once (dual nationals, renewals); the
    # default REPLACE refuses a second held one without naming which ("replace_which").
    document = register(agency.id, student.id, kind="PASSPORT", mode="ADD")
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        DocumentVersion.objects.filter(id=document.id).update(
            state="AVAILABLE", promoted_key=upload_prefix(
                tenant_id=agency.id, student_id=student.id, document_id=document.id
            ) + "scan.pdf", content_type="application/pdf"
        )
    return document


def _run(agency, document, analyze, store=None):
    document_reading.process_document(agency.id, document.id, store=store or _Store(),
                                      analyze=analyze)
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return DocumentReading.objects.get(document_id=document.id)


def test_a_passport_is_read_once_into_facts(agency_a, membership_a):
    membership_a.user.first_name, membership_a.user.last_name = "Nərmin", "Əliyeva"
    membership_a.user.save()
    document = _passport_upload(agency_a, membership_a)
    calls = []

    def analyze(content, *, pages):
        calls.append(pages)
        return passport()

    reading = _run(agency_a, document, analyze)
    assert reading.state == "READ" and reading.facts_written and calls == ["1-4"]
    assert reading.azure_pages == 1
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.filter(
            student=membership_a, category="ID_DOCUMENT", confirmed_at__isnull=False
        ).exists()
    _run(agency_a, document, analyze)  # a redelivery
    assert calls == ["1-4"]


def test_the_same_file_uploaded_again_is_never_read_again(agency_a, membership_a):
    calls = []

    def analyze(content, *, pages):
        calls.append(pages)
        return passport()

    student = _named(membership_a)  # an owner_unknown twin is read again (re-review item 7)
    _run(agency_a, _passport_upload(agency_a, student), analyze)
    second = _run(agency_a, _passport_upload(agency_a, student), analyze)
    assert len(calls) == 1 and second.state == "READ" and second.values


def test_azure_down_delays_and_the_sweep_retries(agency_a, membership_a):
    document = _passport_upload(agency_a, membership_a)

    def down(content, *, pages):
        raise OcrUnavailable("down")

    reading = _run(agency_a, document, down)
    assert reading.state == "DELAYED" and reading.attempts == 1
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.filter(id=reading.id).update(
            next_attempt_at=timezone.now() - timedelta(minutes=1)
        )
    seen = []
    document_reading_process = document_reading.process_document

    def spy(tenant_id, document_id, **kwargs):
        seen.append((document_id, kwargs.get("reading_id")))

    document_reading.process_document = spy
    try:
        call_command("resume_transcript_readings", stdout=StringIO())
    finally:
        document_reading.process_document = document_reading_process
    assert seen == [(document.id, reading.id)]  # the row the sweep found, not the newest


def test_known_names_are_whole_names_never_a_bare_surname(agency_a, membership_a):
    """Spec §5.2.4 as ruled during the build: a one-word value reads as a given name,
    so an earlier passport's surname alone must never be a known name."""
    from django.utils import timezone

    first = _passport_upload(agency_a, membership_a)
    membership_a.user.first_name, membership_a.user.last_name = "Nərmin", "Əliyeva"
    membership_a.user.save()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        for key, value in (("given_names", "NƏRMIN"), ("surname", "ƏLIYEVA")):
            VerifiedFact.objects.create(
                student=membership_a, category="IDENTITY", payload={key: value},
                source_tier="AUTHORITATIVE_DOCUMENT", source_ref=f"document:{first.id}",
                confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a,
            )
        second = _passport_upload(agency_a, membership_a)
        reading = DocumentReading.objects.create(
            student=membership_a, document=second, kind="PASSPORT", reader_version="id-1",
        )
        names = document_reading._known_names(reading)
    assert "Nərmin Əliyeva" in names and "NƏRMIN ƏLIYEVA" in names
    assert "ƏLIYEVA" not in names


def test_not_an_id_document_fails_with_its_code(agency_a, membership_a):
    from tests.documents.id_fixtures import result

    reading = _run(agency_a, _passport_upload(agency_a, membership_a),
                   lambda content, *, pages: result({}, doc_type="invoice"))
    assert (reading.state, reading.failure) == ("FAILED", "not_an_id_document")


def test_the_shared_ceiling_counts_both_readers(agency_a, membership_a, settings, paid_cycle_a):
    from apps.documents.models import TranscriptPage, TranscriptUpload
    from apps.documents.ocr import InventoryPage
    from apps.documents.transcript_pages import _check_ceiling, _OverCeiling

    settings.TRANSCRIPT_TENANT_DAILY_AZURE_PAGES = 6  # a cap of 4 fits alone
    seeded = _passport_upload(agency_a, membership_a)
    transcript = register(agency_a.id, membership_a.id, kind="TRANSCRIPT")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.create(
            student=membership_a, document=seeded, kind="PASSPORT", reader_version="id-1",
            state="READ", azure_pages=2, azure_billed_at=timezone.now(),
        )
        upload = TranscriptUpload.objects.create(
            student=membership_a, cycle=paid_cycle_a, document=transcript, role="ORIGINAL")
        TranscriptPage.objects.create(
            student=membership_a, cycle=paid_cycle_a, upload=upload, number=1, slot=1,
            state="READ", source="azure")
    calls = []

    def analyze(content, *, pages):
        calls.append(pages)
        return passport()

    reading = _run(agency_a, _passport_upload(agency_a, membership_a), analyze)
    assert reading.state == "DELAYED" and calls == []  # 1 + 2 + 4 > 6: only the sum refuses
    page = InventoryPage(number=1, source="image", scan_ppi=None, lines=(), tables=())
    with pytest.raises(_OverCeiling):
        _check_ceiling(agency_a.id, (page,) * 4)  # the transcript side sees document pages


def test_every_azure_answer_counts_toward_the_ceiling(agency_a, membership_a, settings):
    from tests.documents.id_fixtures import result

    settings.TRANSCRIPT_TENANT_DAILY_AZURE_PAGES = 4
    calls = []

    def invoice(content, *, pages):
        calls.append(pages)
        return result({}, doc_type="invoice")

    readings = []
    for body in (b"one", b"two", b"three"):
        readings.append(_run(agency_a, _passport_upload(agency_a, membership_a), invoice,
                             store=_Store(body)))
    assert len(calls) == 1  # 1 page counted + cap 4 > 4 stops the second
    assert [r.state for r in readings] == ["FAILED", "DELAYED", "DELAYED"]
    assert readings[0].azure_pages == 1


def test_a_delayed_then_read_reading_sums_its_pages(agency_a, membership_a):
    from tests.documents.id_fixtures import result

    document = _passport_upload(agency_a, membership_a)
    reading = _run(agency_a, document, lambda c, *, pages: result({}, doc_type="x"))
    # make the first answer a retryable one that was billed: a schema-bad answer
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.filter(id=reading.id).update(
            state="DELAYED", failure="", azure_pages=1, next_attempt_at=None)
    reading = _run(agency_a, document, lambda c, *, pages: passport())
    assert reading.state == "READ" and reading.azure_pages == 2


def test_a_membership_ended_during_the_azure_call_gets_no_facts(agency_a, membership_a):
    from apps.tenancy.models import Membership

    document = _passport_upload(agency_a, membership_a)

    def analyze(content, *, pages):
        with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
            Membership.objects.filter(id=membership_a.id).update(active=False)
        return passport()

    reading = _run(agency_a, document, analyze)
    assert (reading.state, reading.failure) == ("FAILED", "erasure_requested")
    assert reading.azure_pages == 1 and not reading.facts_written
    with tenant_scope(agency_a.id):
        assert not VerifiedFact.objects.filter(student=membership_a).exists()


def test_an_unexpected_error_never_escapes_the_scan_handler(
    agency_a, membership_a, monkeypatch, settings
):
    from apps.documents import document_worker
    from apps.documents.document_queue import ScanResultEvent

    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(document_reading, "read_id", broken)
    monkeypatch.setattr(document_reading, "open_document", lambda d, store=None: b"%PDF-1.7")
    # the scan handler passes no analyze, so replace the keyword default itself
    monkeypatch.setitem(
        document_reading.process_document.__kwdefaults__, "analyze",
        lambda c, *, pages: passport(),
    )
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    document_worker.handle_scan_result(ScanResultEvent(
        object_key=document.object_key, scan_result="NO_THREATS_FOUND",
        bucket_name=settings.EVIDENCE_BUCKET_NAME, version_id="v1"))
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        reading = DocumentReading.objects.get(document_id=document.id)
    assert reading.state == "DELAYED" and reading.attempts == 1


def test_off_means_nothing_is_read_or_queued(agency_a, membership_a, settings):
    settings.FACT_READING_ENABLED = False
    document = _passport_upload(agency_a, membership_a)
    assert not document_reading.queue_reading(agency_a.id, document.id)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert not DocumentReading.objects.exists()


def test_a_clean_scan_of_a_passport_reaches_the_reader(
    agency_a, membership_a, monkeypatch, settings
):
    from apps.documents import document_worker
    from apps.documents.document_queue import ScanResultEvent

    reached = []
    monkeypatch.setattr(document_reading, "process_document",
                        lambda tenant_id, document_id, **k: reached.append(document_id))
    document = register(agency_a.id, membership_a.id, kind="PASSPORT")
    document_worker.handle_scan_result(ScanResultEvent(
        object_key=document.object_key, scan_result="NO_THREATS_FOUND",
        bucket_name=settings.EVIDENCE_BUCKET_NAME, version_id="v1"))
    assert reached == [document.id]


def test_a_racing_correction_retries_instead_of_crashing(agency_a, membership_a, monkeypatch):
    from django.db import IntegrityError

    def boom(reading):
        raise IntegrityError("one superseder")

    monkeypatch.setattr(document_reading, "write_facts", boom)
    document = _passport_upload(agency_a, membership_a)
    reading = _run(agency_a, document, lambda c, *, pages: passport())
    assert reading.state == "DELAYED" and reading.attempts == 1


def _named(student):
    student.user.first_name, student.user.last_name = "Nərmin", "Əliyeva"
    student.user.save()
    return student


def _cv_identity(agency, student):
    """A CV's IDENTITY row built the way ingestion builds it (fact_payload), from a
    CV printing a partial birth date, a sex and a nationality, confirmed by the
    student."""
    from apps.documents.schemas import PersonalInformation
    from apps.documents.verification import fact_payload

    personal = PersonalInformation(
        full_name="Nərmin Əliyeva", email="n@example.com", date_of_birth="1998-03",
        sex="Female", citizenship="Azerbaijani",
    )
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return VerifiedFact.objects.create(
            student=student, category="IDENTITY",
            payload=fact_payload(personal, category="IDENTITY"),
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv",
            confirmed_by=student, confirmed_at=timezone.now(), created_by=student,
        )


@pytest.mark.parametrize("cv_first", [True, False], ids=["cv-then-passport", "passport-then-cv"])
def test_a_cv_never_competes_with_the_passport_for_its_person_keys(
    agency_a, membership_a, cv_first
):
    """Final review, item 1: a CV's "March 1998"/"Female"/"Azerbaijani" outranked the
    check-digit-proven values when it came after the passport, and made every
    passport value a detail to check when it came before."""
    from apps.documents.views import page_context
    from apps.portals.profile import verified_values

    student = _named(membership_a)
    if cv_first:
        cv = _cv_identity(agency_a, student)
    _run(agency_a, _passport_upload(agency_a, student), lambda c, *, pages: passport())
    if not cv_first:
        cv = _cv_identity(agency_a, student)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        values = verified_values(student)
        context = page_context(student, counselor_view=False)
    assert values["identity.date_of_birth"] == "1998-03-14"
    assert values["identity.sex"] == "F"
    assert values["identity.citizenship"] == "Azerbaijan"
    assert values["identity.full_name"] == "Nərmin Əliyeva"
    assert context["to_check"] == []
    for key in ("date_of_birth", "sex", "citizenship", "given_names", "surname",
                "place_of_birth"):
        assert key not in cv.payload


def test_the_same_passport_uploaded_twice_is_one_document(agency_a, membership_a):
    """Final review, item 3: a clearer photo of the same passport asked "Which
    passport should we use?" over two identical buttons and doubled every detail."""
    from apps.documents.verification import id_documents, unsuperseded_facts
    from apps.documents.views import page_context

    student = _named(membership_a)
    first = _passport_upload(agency_a, student)
    _run(agency_a, first, lambda c, *, pages: passport(), store=_Store(b"photo-1"))
    second = _passport_upload(agency_a, student)
    _run(agency_a, second, lambda c, *, pages: passport(), store=_Store(b"photo-2-clearer"))
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        documents = id_documents(unsuperseded_facts(student))
        context = page_context(student, counselor_view=False)
    assert list(documents) == [f"document:{second.id}"]  # the latest read wins
    assert context["passport_choices"] == []
    labels = [row["label"] for row in context["details"]]
    assert labels.count("Document number") == 1 and len(labels) == len(set(labels))


@pytest.mark.parametrize("limit", ["TRANSCRIPT_TENANT_DAILY_AZURE_PAGES", "FACT_READING_HOURLY"])
def test_a_wait_for_a_limit_is_never_an_attempt(agency_a, membership_a, settings, limit):
    """Final review, item 4: twelve waits for the shared ceiling or the hourly limit
    ended FAILED "reader_unavailable" on a passport nothing was wrong with."""
    if limit == "FACT_READING_HOURLY":
        settings.FACT_READING_HOURLY = 0
    else:  # the cap still fits the ceiling (re-review B6b), today's usage does not
        settings.TRANSCRIPT_TENANT_DAILY_AZURE_PAGES = settings.FACT_READING_PAGE_CAPS["PASSPORT"]
        _billed_reading(agency_a, membership_a, pages=1, at=timezone.now())
    document = _passport_upload(agency_a, membership_a)
    for _ in range(MAX_ATTEMPTS + 1):
        with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
            DocumentReading.objects.filter(document=document).update(next_attempt_at=None)
        reading = _run(agency_a, document, lambda c, *, pages: passport())
    assert (reading.state, reading.attempts) == ("DELAYED", 0)
    wait = reading.next_attempt_at - timezone.now()
    assert timedelta(minutes=55) < wait <= timedelta(hours=1)


def test_a_reading_that_ran_out_of_attempts_asks_for_a_new_upload():
    from apps.documents.fact_labels import PROBLEM_TEXT

    assert PROBLEM_TEXT["reader_unavailable"] == "We couldn't read this — upload it again"


@pytest.mark.parametrize(("configured", "billed"), [(True, 4), (False, 0)])
def test_an_azure_failure_after_the_call_bills_the_cap(
    agency_a, membership_a, settings, configured, billed
):
    """Final review, item 6: a failure after the call was attempted may still be
    billed, so the cap is charged -- the safe over-count. Unconfigured, no call
    was ever made."""
    settings.AZURE_DI_ENDPOINT = "https://di.example" if configured else ""
    settings.AZURE_DI_KEY = "key" if configured else ""

    def down(content, *, pages):
        raise OcrUnavailable("Azure analyze timed out")

    reading = _run(agency_a, _passport_upload(agency_a, membership_a), down)
    assert (reading.state, reading.azure_pages) == ("DELAYED", billed)


def _billed_reading(agency, student, *, pages, at):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return DocumentReading.objects.create(
            student=student, document=_passport_upload(agency, student), kind="PASSPORT",
            reader_version="id-1", state="READ", azure_pages=pages, azure_billed_at=at,
        )


def test_the_ceiling_counts_pages_by_when_they_were_billed(agency_a, membership_a):
    """Re-review B6c: counting by updated_at recounted yesterday's pages whenever the
    row was saved again (a passport choice), and could hold a reading for ever."""
    _billed_reading(agency_a, membership_a, pages=4, at=timezone.now() - timedelta(days=1))
    _billed_reading(agency_a, membership_a, pages=2, at=timezone.now())
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert document_reading.azure_pages_today() == 2


def test_a_read_stamps_when_its_pages_were_billed(agency_a, membership_a):
    reading = _run(agency_a, _passport_upload(agency_a, membership_a),
                   lambda c, *, pages: passport())
    assert reading.azure_pages > 0
    assert timezone.now() - reading.azure_billed_at < timedelta(minutes=1)


def test_a_reading_that_can_never_fit_the_ceiling_fails_at_once(agency_a, membership_a, settings):
    settings.TRANSCRIPT_TENANT_DAILY_AZURE_PAGES = settings.FACT_READING_PAGE_CAPS["PASSPORT"] - 1
    calls = []
    reading = _run(agency_a, _passport_upload(agency_a, membership_a),
                   lambda c, *, pages: calls.append(pages) or passport())
    assert (reading.state, reading.failure, calls) == ("FAILED", "reader_unavailable", [])


@pytest.mark.parametrize("limit", ["TRANSCRIPT_TENANT_DAILY_AZURE_PAGES", "FACT_READING_HOURLY"])
def test_a_reading_waiting_past_three_days_asks_for_a_new_upload(
    agency_a, membership_a, settings, limit
):
    if limit == "FACT_READING_HOURLY":
        settings.FACT_READING_HOURLY = 0
    else:
        settings.TRANSCRIPT_TENANT_DAILY_AZURE_PAGES = settings.FACT_READING_PAGE_CAPS["PASSPORT"]
        _billed_reading(agency_a, membership_a, pages=1, at=timezone.now())
    document = _passport_upload(agency_a, membership_a)
    reading = _run(agency_a, document, lambda c, *, pages: passport())
    assert reading.state == "DELAYED"  # a fresh reading waits
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        DocumentReading.objects.filter(id=reading.id).update(
            created_at=timezone.now() - timedelta(days=3), next_attempt_at=None)
    reading = _run(agency_a, document, lambda c, *, pages: passport())
    assert (reading.state, reading.failure) == ("FAILED", "reader_unavailable")
