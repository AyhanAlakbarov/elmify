from datetime import timedelta

import pytest
from django.utils import timezone

from apps.concierge.documents import register, upload_prefix
from apps.concierge.models import DocumentVersion
from apps.documents import document_reading
from apps.documents.fact_readers import ReadersUnavailable
from apps.documents.id_reading import NotRead, ReadValue
from apps.documents.models import DocumentReading, VerifiedFact
from apps.documents.ocr_errors import OcrUnavailable
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _on(settings):
    settings.FACT_READING_ENABLED = True
    settings.TRANSCRIPT_AZURE_ENABLED = True
    settings.FACT_READING_READERS = ["deepseek/a", "openai/b"]
    settings.OPENROUTER_API_KEY = "k"


class _Store:
    def get(self, key):
        return b"%PDF-1.7 certificate"


def _upload(agency, student, kind="LANGUAGE_CERTIFICATE"):
    """As plan 1's tests/documents/test_document_reading.py::_passport_upload: a
    promoted key under the student's own prefix, which open_document checks."""
    document = register(agency.id, student.id, kind=kind)
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        DocumentVersion.objects.filter(id=document.id).update(
            state="AVAILABLE", promoted_key=upload_prefix(
                tenant_id=agency.id, student_id=student.id, document_id=document.id
            ) + "scan.pdf", content_type="application/pdf")
    return document


def _run(agency, document, read_text, **kwargs):
    document_reading.process_document(agency.id, document.id, store=_Store(),
                                      read_text=read_text, **kwargs)
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return DocumentReading.objects.filter(document_id=document.id).order_by(
            "-created_at").first()


def test_a_certificate_is_read_with_the_text_reader_and_the_students_identifiers(
        agency_a, membership_a):
    from tests.documents.conftest import make_identity_fact

    membership_a.user.first_name, membership_a.user.last_name = "Nərmin", "Əliyeva"
    membership_a.user.save()
    with tenant_scope(agency_a.id):
        make_identity_fact(membership_a, full_name="Narmin Aliyeva")
    seen = {}

    def read_text(**kwargs):
        seen.update(kwargs)
        return [ReadValue("language.test_name", "IELTS", "IELTS", True, "readers_agree"),
                ReadValue("language.language", "English", "IELTS", True, "readers_agree")], 1

    reading = _run(agency_a, _upload(agency_a, membership_a), read_text)
    assert reading.state == "READ" and reading.azure_pages == 1
    assert seen["kind"] == "LANGUAGE_CERTIFICATE" and seen["cap"] == 2
    assert "Narmin Aliyeva" in seen["identifiers"]
    assert "Nərmin Əliyeva" in seen["identifiers"]  # the account holder's name (plan 1)
    with tenant_scope(agency_a.id):
        assert VerifiedFact.objects.filter(category="LANGUAGE", student=membership_a).exists()


def test_not_a_certificate_fails_with_its_pages_billed_and_readers_down_delays(
        agency_a, membership_a):
    def not_one(**kwargs):
        kwargs["billed"]["pages"] = 2  # Azure answered before the readers refused it
        raise NotRead("not_a_certificate")

    failed = _run(agency_a, _upload(agency_a, membership_a), not_one)
    assert (failed.state, failed.failure, failed.azure_pages) == ("FAILED", "not_a_certificate", 2)

    def down(**kwargs):
        kwargs["billed"]["pages"] = 1
        raise ReadersUnavailable("TimeoutError")

    delayed = _run(agency_a, _upload(agency_a, membership_a), down)
    assert (delayed.state, delayed.attempts, delayed.azure_pages) == ("DELAYED", 1, 1)


def test_without_a_reader_pair_nothing_is_queued_or_read(agency_a, membership_a, settings):
    settings.FACT_READING_READERS = []
    document = _upload(agency_a, membership_a, kind="DIPLOMA")
    assert not document_reading.kind_enabled("DIPLOMA")
    assert document_reading.kind_enabled("PASSPORT")
    assert not document_reading.queue_reading(agency_a.id, document.id)


def test_a_reading_queued_before_the_pair_was_unset_waits_and_reads_nothing(
        agency_a, membership_a, settings):
    document = _upload(agency_a, membership_a, kind="DIPLOMA")
    assert document_reading.queue_reading(agency_a.id, document.id)
    settings.FACT_READING_READERS = []
    calls = []
    reading = _run(agency_a, document, lambda **k: calls.append(k) or ([], 1))
    assert (reading.state, reading.attempts, calls) == ("DELAYED", 0, [])  # a wait (plan 1)


def test_the_tenants_daily_reader_calls_are_capped(agency_a, membership_a, settings):
    settings.FACT_READING_TENANT_DAILY_CALLS = 0
    calls = []
    reading = _run(agency_a, _upload(agency_a, membership_a),
                   lambda **k: calls.append(k) or ([], 1))
    assert (reading.state, reading.attempts, calls) == ("DELAYED", 0, [])


def test_the_sweep_acts_on_the_reading_it_found(agency_a, membership_a):
    """Carried from plan 1's Task 7 review: with two reader versions of one document,
    the sweep's DELAYED row is the one claimed -- not whichever row is newest."""
    document = _upload(agency_a, membership_a)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        old = DocumentReading.objects.create(
            student=membership_a, document=document, kind="LANGUAGE_CERTIFICATE",
            reader_version="doc-0", state="DELAYED",
            next_attempt_at=timezone.now() - timedelta(minutes=1))
        DocumentReading.objects.create(
            student=membership_a, document=document, kind="LANGUAGE_CERTIFICATE",
            reader_version="doc-1", state="READ", values=[])
    _run(agency_a, document, lambda **k: ([], 1), reading_id=old.id)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        old.refresh_from_db()
    assert old.state == "READ"


def test_a_certificate_never_reuses_a_diplomas_reading_of_the_same_file(agency_a, membership_a):
    """Both kinds are reader version doc-1: the twin shortcut must match on kind too."""
    calls = []

    def read_text(**kwargs):
        calls.append(kwargs["kind"])
        if kwargs["kind"] == "DIPLOMA":
            return [ReadValue("education.institution_original", "Baku State University",
                              "Baku State University", True, "readers_agree")], 1
        return [ReadValue("language.test_name", "IELTS", "IELTS", True, "readers_agree")], 1

    _run(agency_a, _upload(agency_a, membership_a, kind="DIPLOMA"), read_text)
    second = _run(agency_a, _upload(agency_a, membership_a), read_text)
    assert calls == ["DIPLOMA", "LANGUAGE_CERTIFICATE"]
    assert [v["key"] for v in second.values] == ["language.test_name"]


def test_a_reading_waiting_for_the_pair_never_spends_the_students_hour(
        agency_a, membership_a, settings):
    document = _upload(agency_a, membership_a, kind="DIPLOMA")
    assert document_reading.queue_reading(agency_a.id, document.id)
    settings.FACT_READING_READERS = []
    settings.FACT_READING_HOURLY = 1
    for _ in range(2):
        with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
            DocumentReading.objects.filter(document_id=document.id).update(
                state="DELAYED", next_attempt_at=None)
        _run(agency_a, document, lambda **k: ([], 1))
    analysed = []

    def analyze(content, *, pages):
        analysed.append(pages)
        raise OcrUnavailable("down")

    _run(agency_a, _upload(agency_a, membership_a, kind="PASSPORT"), None, analyze=analyze)
    assert analysed == ["1-4"]  # the student's one reading this hour was still there


def test_the_readers_never_see_the_students_contact_or_id_details(agency_a, membership_a):
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        membership_a.application_email = "narmin.apply@example.com"
        membership_a.save(update_fields=["application_email"])
        VerifiedFact.objects.create(
            student=membership_a, category="IDENTITY",
            payload={"full_name": "Narmin Aliyeva", "phone": "+994 50 123 45 67",
                     "date_of_birth": "2001-03-04", "place_of_birth": "Ganja"},
            source_tier="STUDENT_STATEMENT", source_ref="upload:cv", created_by=membership_a)
        VerifiedFact.objects.create(
            student=membership_a, category="ID_DOCUMENT", payload={"number": "C01234567"},
            source_tier="AUTHORITATIVE_DOCUMENT", source_ref="document:x",
            created_by=membership_a)
    seen = {}
    _run(agency_a, _upload(agency_a, membership_a), lambda **k: seen.update(k) or ([], 1))
    for value in ("2001-03-04", "C01234567", "+994 50 123 45 67", "narmin.apply@example.com"):
        assert value in seen["identifiers"]
    assert "Ganja" not in seen["identifiers"]  # it would strip "Ganja State University"


def test_the_passport_path_builds_no_identifiers(agency_a, membership_a, monkeypatch):
    built = []
    monkeypatch.setattr(document_reading, "_identifiers", lambda *a: built.append(a) or [])

    def analyze(content, *, pages):
        raise OcrUnavailable("down")

    _run(agency_a, _upload(agency_a, membership_a, kind="PASSPORT"), None, analyze=analyze)
    assert built == []


def test_readers_off_schema_fail_the_reading_and_transport_errors_delay(agency_a, membership_a):
    def off_schema(**kwargs):
        kwargs["billed"]["pages"] = 1
        raise ReadersUnavailable("off_schema")

    failed = _run(agency_a, _upload(agency_a, membership_a), off_schema)
    assert (failed.state, failed.failure, failed.azure_pages) == (
        "FAILED", "reader_unavailable", 1)  # never re-billed for a model that keeps failing

    def connection(**kwargs):
        kwargs["billed"]["pages"] = 1
        raise ReadersUnavailable("ConnectionError")

    delayed = _run(agency_a, _upload(agency_a, membership_a), connection)
    assert (delayed.state, delayed.failure) == ("DELAYED", "")


def test_a_failure_never_overwrites_a_reading_another_worker_finished(agency_a, membership_a):
    document = _upload(agency_a, membership_a)

    def finished_meanwhile(**kwargs):
        # The lease expired, another worker read it, and only then did this read fail.
        with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
            DocumentReading.objects.filter(document_id=document.id).update(
                state="READ", values=[])
        kwargs["billed"]["pages"] = 1
        raise NotRead("not_a_certificate")

    reading = _run(agency_a, document, finished_meanwhile)
    assert (reading.state, reading.failure) == ("READ", "")
