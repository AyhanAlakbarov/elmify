import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.conf import settings

from apps.concierge.documents import open_document, register
from apps.concierge.models import UPLOAD_REJECTIONS, DocumentVersion
from apps.documents import document_worker
from apps.documents.document_queue import ScanResultEvent
from apps.documents.ocr import UploadVerdict
from apps.documents.ocr_errors import OcrUnavailable
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.7 passport scan"
#: The digest the fake check answers with when a test does not choose one: that of exactly the
#: bytes it was handed, as the real inspect() does.
HANDED = "0" * 64
CLEAN = UploadVerdict(type="application/pdf", active_content=(), sha256=HANDED)
NOT_ALLOWED = UploadVerdict(type=None, active_content=(), sha256=HANDED)


@pytest.fixture(autouse=True)
def _uploads_pass_the_upload_check():
    """Overrides tests/documents/conftest.py's stub: this module is about the real check."""


@pytest.fixture
def bucket(monkeypatch, fake_store):
    monkeypatch.setattr(document_worker, "_object_store", lambda: fake_store)
    return fake_store


@pytest.fixture
def ingested(monkeypatch):
    calls = []
    monkeypatch.setattr(
        document_worker, "ingest_uploaded_cv", lambda **kwargs: calls.append(kwargs) or ()
    )
    return calls


@pytest.fixture
def check(monkeypatch):
    """The isolated function's answer, set per test. What it was handed is recorded, and
    the state every other reader could see while it ran -- the committed row."""
    state = SimpleNamespace(answer=CLEAN, handed=[], committed=[], during=None)

    def _inspect(document, content):
        state.handed.append(content)
        with tenant_scope(document.tenant_id), tenant_transaction(document.tenant_id):
            state.committed.append(DocumentVersion.objects.get(id=document.id).state)
        if isinstance(state.answer, Exception):
            raise state.answer
        if state.during is not None:
            state.during(document)
        if state.answer.sha256 == HANDED:
            return state.answer.model_copy(
                update={"sha256": hashlib.sha256(content).hexdigest()}
            )
        return state.answer

    monkeypatch.setattr(document_worker, "inspect_upload", _inspect)
    return state


def _event(document, status="NO_THREATS_FOUND", version="test-version-1") -> ScanResultEvent:
    """`version` is the one GuardDuty scanned: the first put of the key, unless a test says."""
    return ScanResultEvent(
        object_key=document.object_key, scan_result=status,
        bucket_name=settings.EVIDENCE_BUCKET_NAME, version_id=version,
    )


def _uploaded(agency, student, bucket, body=PDF, kind="PASSPORT"):
    document = register(agency.id, student.id, kind=kind)
    bucket.put(document.object_key, body)
    return document


def _reloaded(document):
    with tenant_scope(document.tenant_id):
        document.refresh_from_db()
    return document


def test_a_clean_upload_is_copied_under_the_students_prefix_byte_for_byte(
    agency_a, membership_a, bucket, check
):
    document = _uploaded(agency_a, membership_a, bucket)

    document_worker.handle_scan_result(_event(document))

    document = _reloaded(document)
    prefix = f"tenants/{agency_a.id}/students/{membership_a.id}/uploads/{document.id}/"
    assert document.promoted_key.startswith(prefix)
    assert bucket.get(document.promoted_key) == PDF
    assert (document.state, document.content_type) == ("AVAILABLE", "application/pdf")
    assert check.handed == [PDF]
    # While the check ran, nothing could read the upload as usable.
    assert check.committed == ["CHECKING"]


def test_a_file_of_another_type_is_rejected_never_copied_and_never_read_as_a_cv(
    agency_a, membership_a, bucket, check, ingested
):
    """The check's type, never the name: an HTML page called cv.pdf stops here."""
    document = _uploaded(agency_a, membership_a, bucket, body=b"<html>", kind="CV")
    check.answer = NOT_ALLOWED

    document_worker.handle_scan_result(_event(document))

    document = _reloaded(document)
    assert (document.state, document.promoted_key) == ("REJECTED_TYPE", "")
    assert document.rejection_message.startswith("Upload a PDF, JPEG or PNG")
    assert ingested == []


def test_a_pdf_with_active_content_is_rejected_and_never_copied(
    agency_a, membership_a, bucket, check
):
    document = _uploaded(agency_a, membership_a, bucket)
    check.answer = UploadVerdict(
        type="application/pdf", active_content=("/Launch", "/OpenAction"), sha256=HANDED
    )

    document_worker.handle_scan_result(_event(document))

    document = _reloaded(document)
    assert (document.state, document.promoted_key) == ("REJECTED_ACTIVE_CONTENT", "")
    assert document.rejection_message == UPLOAD_REJECTIONS["REJECTED_ACTIVE_CONTENT"]
    assert "Print → Save as PDF" in document.rejection_message


def test_a_redelivered_clean_verdict_never_reopens_a_rejected_upload(
    agency_a, membership_a, bucket, check
):
    document = _uploaded(agency_a, membership_a, bucket)
    check.answer = NOT_ALLOWED
    document_worker.handle_scan_result(_event(document))
    check.answer = CLEAN
    document_worker.handle_scan_result(_event(document))
    assert _reloaded(document).state == "REJECTED_TYPE"
    assert len(check.handed) == 1


def test_a_blocked_upload_is_never_checked_or_copied(agency_a, membership_a, bucket, check):
    document = _uploaded(agency_a, membership_a, bucket)
    document_worker.handle_scan_result(_event(document, "THREATS_FOUND"))
    assert _reloaded(document).promoted_key == ""
    assert check.handed == []


def test_a_redelivered_clean_verdict_checks_and_copies_once(
    agency_a, membership_a, bucket, check
):
    document = _uploaded(agency_a, membership_a, bucket)
    document_worker.handle_scan_result(_event(document))
    document_worker.handle_scan_result(_event(document))
    assert len(check.handed) == 1


def test_a_check_that_does_not_answer_promotes_nothing_and_ends_review_required(
    agency_a, membership_a, bucket, check, ingested
):
    """Never clean by default: CHECKING until the last retry, then REVIEW_REQUIRED."""
    document = _uploaded(agency_a, membership_a, bucket, kind="CV")
    check.answer = OcrUnavailable("exit 1")
    with pytest.raises(OcrUnavailable):
        document_worker.handle_scan_result(_event(document))
    assert (_reloaded(document).state, document.promoted_key) == ("CHECKING", "")
    assert ingested == []

    document_worker.mark_read_failed(_event(document))
    assert _reloaded(document).state == "REVIEW_REQUIRED"


def test_the_poll_says_what_to_do_with_a_rejected_upload(
    client, agency_a, domain_a, user_a, membership_a, bucket, check
):
    document = _uploaded(agency_a, membership_a, bucket)
    check.answer = NOT_ALLOWED
    document_worker.handle_scan_result(_event(document))
    client.force_login(user_a)
    body = client.get(f"/api/documents/uploads/{document.id}", HTTP_HOST=domain_a.host).json()
    assert body == {
        "state": "REJECTED_TYPE",
        "scan_result": "NO_THREATS_FOUND",
        "message": "Upload a PDF, JPEG or PNG",
    }


def _uploads_written(bucket, document):
    prefix = f"tenants/{document.tenant_id}/students/{document.student_id}/uploads/"
    return [key for key in bucket._data if key.startswith(prefix)]


def test_the_scanned_version_is_checked_and_copied_never_a_later_upload(
    agency_a, membership_a, bucket, check
):
    """The upload form stays valid for 900 s: a second POST to the same key after the scan
    is a new, unscanned version. Only the version the scan named is read, checked and copied."""
    document = _uploaded(agency_a, membership_a, bucket)
    bucket.put(document.object_key, b"%PDF-1.7 swapped in after the scan")

    document_worker.handle_scan_result(_event(document, version="test-version-1"))

    document = _reloaded(document)
    assert check.handed == [PDF]
    assert bucket.get(document.promoted_key) == PDF
    assert document.scanned_version == "test-version-1"


def test_a_check_that_judged_other_bytes_promotes_nothing(
    agency_a, membership_a, bucket, check
):
    check.answer = CLEAN.model_copy(update={"sha256": "f" * 64})
    document = _uploaded(agency_a, membership_a, bucket)

    document_worker.handle_scan_result(_event(document))

    document = _reloaded(document)
    assert (document.state, document.promoted_key) == ("REVIEW_REQUIRED", "")
    assert _uploads_written(bucket, document) == []


def test_a_verdict_naming_no_version_promotes_nothing(agency_a, membership_a, bucket, check):
    document = _uploaded(agency_a, membership_a, bucket)

    document_worker.handle_scan_result(_event(document, version=None))

    document = _reloaded(document)
    assert (document.state, document.promoted_key) == ("REVIEW_REQUIRED", "")
    assert check.handed == []


def test_a_threat_with_an_empty_version_is_still_blocked(agency_a, membership_a, bucket, check):
    document = _uploaded(agency_a, membership_a, bucket)
    document_worker.handle_scan_result(_event(document, "THREATS_FOUND", version=""))
    assert (_reloaded(document).state, check.handed) == ("BLOCKED", [])


@pytest.mark.parametrize("answer", [CLEAN, NOT_ALLOWED])
def test_a_verdict_written_while_the_check_ran_is_never_overwritten(
    agency_a, membership_a, bucket, check, answer
):
    """A THREATS_FOUND for a re-upload lands while the check of the first version is in
    flight. The check's outcome is written only over CHECKING, and decided before the copy."""
    document = _uploaded(agency_a, membership_a, bucket)

    def _blocked_meanwhile(document):
        with tenant_scope(document.tenant_id), tenant_transaction(document.tenant_id):
            DocumentVersion.objects.filter(id=document.id).update(
                state="BLOCKED", scan_result="THREATS_FOUND"
            )

    check.answer, check.during = answer, _blocked_meanwhile
    document_worker.handle_scan_result(_event(document))

    document = _reloaded(document)
    assert (document.state, document.promoted_key) == ("BLOCKED", "")
    assert _uploads_written(bucket, document) == []


def test_a_cv_that_is_not_a_pdf_jpeg_or_png_is_told_to_export_a_pdf(
    agency_a, membership_a, bucket, check, ingested
):
    """Owner, 2026-10-05: every upload is one of the three, a CV included -- a Word CV is
    refused at the check, with what to do, and never reaches the DOCX parser."""
    document = _uploaded(agency_a, membership_a, bucket, body=b"PK\x03\x04word", kind="CV")
    check.answer = NOT_ALLOWED

    document_worker.handle_scan_result(_event(document))

    document = _reloaded(document)
    assert document.state == "REJECTED_TYPE"
    assert "export it as a PDF" in document.rejection_message
    assert ingested == []


def test_after_promotion_every_reader_gets_the_checked_copy(
    agency_a, membership_a, bucket, check
):
    """A re-upload through the still-valid form is a newer quarantine version nobody checked:
    open_document -- CV ingestion, the transcript read, evidence intake -- reads the
    promoted copy, never the quarantine key."""
    document = _uploaded(agency_a, membership_a, bucket)
    document_worker.handle_scan_result(_event(document))
    bucket.put(document.object_key, b"<html><script>alert(1)</script>")

    with tenant_scope(agency_a.id):
        assert open_document(_reloaded(document), store=bucket) == PDF


_OCR_VENV = Path(settings.OCR_PYTHON)


@pytest.mark.skipif(not _OCR_VENV.exists(), reason="no OCR venv: uv sync --project ocr")
class TestTheRealCheck:
    """The real ocr/read_pages.py --inspect child, over PDFs pypdf wrote. No model loads."""

    @pytest.fixture(autouse=True)
    def _child(self, monkeypatch):
        monkeypatch.setattr(settings, "OCR_FUNCTION_NAME", "")
        monkeypatch.syspath_prepend(str(settings.BASE_DIR / "ocr"))  # for pdf_fixtures

    @pytest.mark.parametrize(
        "name",
        ["open_action_javascript", "embedded_file", "launch", "xfa", "open_action_uri",
         "page_action_submit_form", "cyclic_next"],
    )
    def test_an_active_pdf_is_rejected(self, agency_a, membership_a, bucket, name):
        import pdf_fixtures

        edit, _named = pdf_fixtures.ACTIVE[name]
        document = _uploaded(agency_a, membership_a, bucket, body=pdf_fixtures.written(edit))
        document_worker.handle_scan_result(_event(document))
        document = _reloaded(document)
        assert (document.state, document.promoted_key) == ("REJECTED_ACTIVE_CONTENT", "")

    @pytest.mark.parametrize("signed", [False, True])
    def test_a_plain_or_signed_pdf_is_promoted_byte_identical(
        self, agency_a, membership_a, bucket, signed
    ):
        import pdf_fixtures

        body = pdf_fixtures.written(pdf_fixtures.signature_field if signed else lambda w: None)
        document = _uploaded(agency_a, membership_a, bucket, body=body)
        document_worker.handle_scan_result(_event(document))
        document = _reloaded(document)
        assert document.state == "AVAILABLE"
        assert bucket.get(document.promoted_key) == body

    def test_a_link_the_reader_clicks_is_promoted(self, agency_a, membership_a, bucket):
        import pdf_fixtures

        body = pdf_fixtures.written(pdf_fixtures.link_uri)
        document = _uploaded(agency_a, membership_a, bucket, body=body)
        document_worker.handle_scan_result(_event(document))
        document = _reloaded(document)
        assert document.state == "AVAILABLE"
        assert bucket.get(document.promoted_key) == body

    def test_an_html_file_named_passport_pdf_is_rejected(self, agency_a, membership_a, bucket):
        document = _uploaded(agency_a, membership_a, bucket, body=b"<html><script>1</script>")
        document_worker.handle_scan_result(_event(document))
        assert _reloaded(document).state == "REJECTED_TYPE"


@pytest.fixture
def passport_a(agency_a, membership_a, bucket):
    """Written as the superuser, before rls_enforced_orm reconnects."""
    return _uploaded(agency_a, membership_a, bucket)


def _behind_the_policy(document):
    with tenant_scope(document.tenant_id), tenant_transaction(document.tenant_id):
        row = DocumentVersion._base_manager.get(id=document.id)
    return row.state, row.promoted_key != ""


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("answer", "stored"),
    [
        (CLEAN, ("AVAILABLE", True)),
        (NOT_ALLOWED, ("REJECTED_TYPE", False)),
        (UploadVerdict(type="application/pdf", active_content=("/JS",), sha256=HANDED),
         ("REJECTED_ACTIVE_CONTENT", False)),
    ],
)
def test_every_outcome_of_the_check_is_written_behind_the_policy(
    passport_a, check, rls_enforced_orm, answer, stored
):
    """An UPDATE with the GUC unset matches zero rows and raises nothing (CLAUDE.md failure
    mode 1): a promoted upload would stay CHECKING, a rejected one would never say why."""
    check.answer = answer
    document_worker.handle_scan_result(_event(passport_a))
    assert _behind_the_policy(passport_a) == stored


@pytest.mark.django_db(transaction=True)
def test_an_unanswered_check_ends_review_required_behind_the_policy(
    passport_a, check, rls_enforced_orm
):
    check.answer = OcrUnavailable("exit 1")
    with pytest.raises(OcrUnavailable):
        document_worker.handle_scan_result(_event(passport_a))
    assert _behind_the_policy(passport_a) == ("CHECKING", False)
    document_worker.mark_read_failed(_event(passport_a))
    assert _behind_the_policy(passport_a) == ("REVIEW_REQUIRED", False)
