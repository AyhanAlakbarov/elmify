"""A transcript upload is read into pages and a stored reading, and never reaches CV ingestion."""

import json
from contextlib import ExitStack
from dataclasses import replace
from datetime import date
from unittest.mock import patch

import pytest
from django.conf import settings

from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.documents.document_queue import (
    MAX_RECEIVES,
    DocumentWorkMessage,
    ScanResultEvent,
    consume_once,
)
from apps.documents.document_worker import handle_scan_result, mark_read_failed
from apps.documents.models import TranscriptReading, TranscriptUpload, VerifiedFact
from apps.documents.ocr import PageRead
from apps.documents.ocr_errors import OcrUnavailable
from apps.documents.transcript import (
    Reading,
    Row,
    TranscriptContent,
    TranscriptCourse,
    TranscriptReadingDisabled,
)
from apps.research.decisions import DecisionsUnavailable
from apps.tenancy.context import tenant_scope
from tests.documents.test_transcript_pages import PNG, _inv, _page

pytestmark = pytest.mark.django_db

UPLOADS = "/api/documents/uploads"
PAGES = "apps.documents.transcript_pages."


def _reading():
    return Reading(
        content=TranscriptContent(
            institution="Baku State University",
            country_code="AZ",
            qualification="BSc",
            field="Chemistry",
            overall_grade="88",
            grading_scale="100",
            credit_unit="ECTS",
            courses=(TranscriptCourse(title="Organic Chemistry I", credits=6, status="COMPLETED"),),
            expected_completion=date(2027, 6, 30),
        ),
        rows=(Row(0, "course", "Organic Chemistry I", "6", "91", "COMPLETED"),),
        total_credits_line=None,
        doubts=(),
    )


def _event(document):
    return ScanResultEvent(
        bucket_name=settings.EVIDENCE_BUCKET_NAME,
        object_key=document.object_key,
        scan_result="NO_THREATS_FOUND",
    )


def _transcript(agency, membership, cycle, *, state=None):
    """A transcript registered the way the upload API does: a document and its upload."""
    document = register(agency.id, membership.id, kind="TRANSCRIPT")
    with tenant_scope(agency.id):
        TranscriptUpload.objects.create(
            student=membership, cycle=cycle, document=document, role="ORIGINAL",
            **({"state": state} if state else {}),
        )
    return document


def _upload(document):
    with tenant_scope(document.tenant_id):
        return TranscriptUpload.objects.get(document=document)


def _pipeline(stack, *, reading=None):
    """The slow seams of transcript_pages, replaced: the file, the inventory, Azure and Jev."""
    return {
        "inventory": stack.enter_context(patch(PAGES + "inventory", return_value=_inv(1))),
        "read": stack.enter_context(
            patch(PAGES + "read_inventory", return_value=(PageRead(1, page=_page()),))
        ),
        "jev": stack.enter_context(
            patch(PAGES + "read_from_pages", return_value=reading or _reading())
        ),
        "open": stack.enter_context(patch(PAGES + "open_document", return_value=PNG)),
        "gates": stack.enter_context(patch(PAGES + "check_gates")),
    }


def test_a_redelivered_scan_event_reads_nothing_and_charges_once(
    agency_a, membership_a, paid_cycle_a
):
    document = _transcript(agency_a, membership_a, paid_cycle_a)
    with ExitStack() as stack, patch("apps.documents.document_worker.ingest_uploaded_cv") as ingest:
        seams = _pipeline(stack)
        handle_scan_result(_event(document))
        handle_scan_result(_event(document))  # SQS redelivers
    assert (seams["inventory"].call_count, seams["jev"].call_count) == (1, 1)
    ingest.assert_not_called()
    with tenant_scope(agency_a.id):
        paid_cycle_a.refresh_from_db()
        assert paid_cycle_a.pages_used == 1
        assert TranscriptReading.objects.filter(document=document).count() == 1
        reading = TranscriptReading.objects.get(document=document)
        assert reading.cycle_id == paid_cycle_a.id
        assert reading.record["courses"][0]["ects"] == "6.00"
        assert reading.highlights == [
            {"kind": "credit_total_not_checked", "scope": "transcript", "ref": ""}
        ]
        assert reading.key_numbers["total_credits"] == "6"
        assert reading.key_numbers["graduation_date"] == "2027-06-30"
        assert reading.accepted is None
        assert not VerifiedFact.objects.filter(student=membership_a).exists()


def test_a_transcript_registered_outside_the_upload_api_is_never_read(agency_a, membership_a):
    document = register(agency_a.id, membership_a.id, kind="TRANSCRIPT")
    with patch("apps.documents.document_worker.process_upload") as process:
        handle_scan_result(_event(document))
    process.assert_not_called()
    with tenant_scope(agency_a.id):
        document.refresh_from_db()
        assert document.state == "READ_FAILED"
        assert not TranscriptReading.objects.exists()


def test_the_worker_hands_a_clean_transcript_to_process_upload(
    agency_a, membership_a, paid_cycle_a
):
    document = _transcript(agency_a, membership_a, paid_cycle_a)
    with patch("apps.documents.document_worker.process_upload") as process:
        handle_scan_result(_event(document))
    process.assert_called_once_with(agency_a.id, _upload(document).id)


def test_a_closed_launch_gate_fails_the_upload_without_crashing_or_opening_the_file(
    agency_a, membership_a, paid_cycle_a
):
    """TranscriptReadingDisabled cannot be fixed by a retry: it must not crash the worker, page
    the alarm or cost redeliveries -- the upload is FAILED on the first delivery, unopened."""
    document = _transcript(agency_a, membership_a, paid_cycle_a)
    with (
        patch(PAGES + "check_gates", side_effect=TranscriptReadingDisabled("off")),
        patch(PAGES + "open_document") as opened,
    ):
        handle_scan_result(_event(document))  # does not raise
    opened.assert_not_called()
    upload = _upload(document)
    assert (upload.state, upload.refusal) == ("FAILED", "reading_off")
    with tenant_scope(agency_a.id):
        assert not TranscriptReading.objects.filter(document=document).exists()


def test_an_engine_that_did_not_answer_delays_the_upload_without_crashing(
    agency_a, membership_a, paid_cycle_a
):
    """Azure down is a delay for the resume sweep, not a crash and not another engine: the
    verdict stays written and the message is consumed."""
    document = _transcript(agency_a, membership_a, paid_cycle_a)
    with (
        patch(PAGES + "check_gates"),
        patch(PAGES + "open_document", return_value=PNG),
        patch(PAGES + "inventory", side_effect=OcrUnavailable("x")),
    ):
        handle_scan_result(_event(document))  # does not raise
    upload = _upload(document)
    assert (upload.state, upload.attempts) == ("DELAYED", 1)
    with tenant_scope(agency_a.id):
        document.refresh_from_db()
        assert document.state == "AVAILABLE"
        assert not TranscriptReading.objects.exists()


def test_every_row_and_semester_highlight_names_a_row_the_reading_stores(
    agency_a, membership_a, paid_cycle_a
):
    """A highlight's ref is a row index. Stored without the rows, "row 1" and "the semester
    whose total is row 2" named nothing the summary screen could show."""
    rows = (
        Row(0, "semester_heading", "Semester 1", "", "", None),
        Row(1, "course", "Organic Chemistry I", "60", "91", "COMPLETED"),
        Row(2, "semester_total", "Total", "6", "", None),
    )
    document = _transcript(agency_a, membership_a, paid_cycle_a)
    with ExitStack() as stack:
        _pipeline(stack, reading=replace(_reading(), rows=rows))
        handle_scan_result(_event(document))
    with tenant_scope(agency_a.id):
        reading = TranscriptReading.objects.get(document=document)
    stored = {row["index"]: row for row in reading.rows}
    pointed = [h for h in reading.highlights if h["scope"] in ("row", "semester")]
    assert {(h["kind"], h["scope"], h["ref"]) for h in pointed} == {
        ("credit_out_of_range", "row", "1"),
        ("credit_total_mismatch", "semester", "2"),
    }
    assert all(int(h["ref"]) in stored for h in pointed)
    assert stored[1] == {
        "index": 1,
        "kind": "course",
        "title": "Organic Chemistry I",
        "credits": "60",
        "grade": "91",
        "status": "COMPLETED",
    }
    assert stored[0]["kind"] == "semester_heading"


class _Queue:
    """One scan verdict, delivered for the `receives`-th time."""

    def __init__(self, document, receives):
        self.body = _event(document).model_dump_json()
        self.receives = receives
        self.deleted = False

    def receive_message(self, **kwargs):
        return {
            "Messages": [
                {
                    "Body": self.body,
                    "ReceiptHandle": "r",
                    "Attributes": {"ApproximateReceiveCount": str(self.receives)},
                }
            ]
        }

    def delete_message(self, **kwargs):
        self.deleted = True

    def send_message(self, **kwargs):
        raise AssertionError("the worker sends nothing")


def _deliver(document, receives, error):
    """One delivery whose process_upload raised `error`, the upload being mid-read."""
    queue = _Queue(document, receives)
    with tenant_scope(document.tenant_id):
        TranscriptUpload.objects.filter(document=document).update(state="READING")
    with (
        patch("apps.documents.document_worker.process_upload", side_effect=error),
        pytest.raises(type(error)),
    ):
        consume_once(
            client=queue,
            queue_url="q",
            handler=handle_scan_result,
            message_type=ScanResultEvent,
            on_last_failure=mark_read_failed,
        )
    assert not queue.deleted
    return _upload(document)


@pytest.mark.parametrize(
    "error", [OcrUnavailable("x"), DecisionsUnavailable("x"), KeyError("credit_system")]
)
def test_the_last_failed_delivery_delays_the_upload_never_fails_it(
    agency_a, membership_a, paid_cycle_a, error
):
    """Whatever escaped process_upload, the last delivery leaves the upload DELAYED for the
    resume sweep -- which fails it after MAX_ATTEMPTS -- never READ_FAILED."""
    document = _transcript(agency_a, membership_a, paid_cycle_a)
    for receives in range(1, MAX_RECEIVES):
        assert _deliver(document, receives, error).attempts == 0
    upload = _deliver(document, MAX_RECEIVES, error)
    assert (upload.state, upload.attempts) == ("DELAYED", 1)
    assert upload.next_attempt_at is not None
    with tenant_scope(agency_a.id):
        document.refresh_from_db()
        assert document.state == "AVAILABLE"
        assert not TranscriptReading.objects.filter(document=document).exists()


def test_the_last_failure_never_touches_a_cv_or_a_transcript_already_read(
    agency_a, membership_a, paid_cycle_a
):
    cv = register(agency_a.id, membership_a.id)
    read = _transcript(agency_a, membership_a, paid_cycle_a)
    with ExitStack() as stack:
        _pipeline(stack)
        handle_scan_result(_event(read))
    with patch("apps.documents.document_worker.ingest_uploaded_cv"):
        handle_scan_result(_event(cv))
    mark_read_failed(_event(cv))
    mark_read_failed(_event(read))
    with tenant_scope(agency_a.id):
        cv.refresh_from_db()
        read.refresh_from_db()
    upload = _upload(read)
    assert (cv.state, read.state) == ("AVAILABLE", "AVAILABLE")
    assert (upload.state, upload.attempts) == ("READ", 0)


def test_a_cv_upload_still_goes_to_cv_ingestion(agency_a, membership_a):
    document = register(agency_a.id, membership_a.id)
    with (
        patch("apps.documents.document_worker.ingest_uploaded_cv") as ingest,
        patch("apps.documents.document_worker.process_upload") as process,
    ):
        handle_scan_result(_event(document))
    assert ingest.call_count == 1 and process.call_count == 0


def _presign(monkeypatch):
    import apps.documents.api as api

    monkeypatch.setattr(api, "presigned_upload", lambda document: {"url": "u", "fields": {}})


@pytest.mark.parametrize("kind", ["SELFIE", ["CV"], {"kind": "CV"}])
def test_the_upload_endpoint_refuses_an_unknown_kind(
    client, domain_a, user_a, membership_a, monkeypatch, kind
):
    """A list or dict is unhashable: tested against the set first, it was a 500."""
    _presign(monkeypatch)
    client.force_login(user_a)
    response = client.post(
        UPLOADS,
        data=json.dumps({"kind": kind}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_kind"


def test_the_upload_endpoint_stores_a_transcript_kind(
    client, domain_a, user_a, membership_a, agency_a, monkeypatch, paid_cycle_a
):
    _presign(monkeypatch)
    client.force_login(user_a)
    response = client.post(
        UPLOADS,
        data=json.dumps({"kind": "TRANSCRIPT", "role": "ORIGINAL"}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 201
    with tenant_scope(agency_a.id):
        assert DocumentVersion.objects.get(id=response.json()["document_id"]).kind == "TRANSCRIPT"


def _get(client, domain, path):
    return client.get(path, HTTP_HOST=domain.host)


def test_the_poll_and_the_transcript_report_a_finished_reading(
    client, domain_a, user_a, membership_a, agency_a, paid_cycle_a
):
    """The poll's `reading` is the upload's own state; the transcript's `reading_id` is the
    cycle's newest reading, and `waiting`/`delayed` say another upload is still on its way."""
    document = _transcript(agency_a, membership_a, paid_cycle_a)
    with ExitStack() as stack:
        _pipeline(stack)
        handle_scan_result(_event(document))
    client.force_login(user_a)
    poll = _get(client, domain_a, f"{UPLOADS}/{document.id}").json()
    assert poll == {
        "state": "AVAILABLE",
        "scan_result": "NO_THREATS_FOUND",
        "reading": {"state": "READ", "refusal": "", "refusal_page": None},
    }
    summary = _get(client, domain_a, "/api/documents/transcript").json()
    assert summary["reading_id"] is not None
    assert (summary["waiting"], summary["delayed"]) == (False, False)

    _transcript(agency_a, membership_a, paid_cycle_a, state="READING")
    summary = _get(client, domain_a, "/api/documents/transcript").json()
    assert (summary["waiting"], summary["delayed"]) == (True, False)
    _transcript(agency_a, membership_a, paid_cycle_a, state="DELAYED")
    summary = _get(client, domain_a, "/api/documents/transcript").json()
    assert (summary["waiting"], summary["delayed"]) == (True, True)


def test_the_transcript_counts_pages_read_but_not_yet_assembled(
    client, domain_a, user_a, membership_a, agency_a, paid_cycle_a
):
    """Pages written and a reading still to be built -- or waiting on Jev -- is not done."""
    from datetime import timedelta

    from django.utils import timezone

    document = _transcript(agency_a, membership_a, paid_cycle_a, state="READ")
    client.force_login(user_a)
    summary = _get(client, domain_a, "/api/documents/transcript").json()
    assert (summary["waiting"], summary["delayed"]) == (True, False)
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(document=document).update(
            next_attempt_at=timezone.now() + timedelta(minutes=5)
        )
    summary = _get(client, domain_a, "/api/documents/transcript").json()
    assert (summary["waiting"], summary["delayed"]) == (True, True)
    with tenant_scope(agency_a.id):
        TranscriptUpload.objects.filter(document=document).update(
            assembled=True, next_attempt_at=None
        )
    summary = _get(client, domain_a, "/api/documents/transcript").json()
    assert (summary["waiting"], summary["delayed"]) == (False, False)


def test_the_poll_reports_an_upload_waiting_for_the_reader(
    client, domain_a, user_a, membership_a, agency_a, paid_cycle_a
):
    """Distinct from "failed": the upload flow says the reading is delayed, not that it died."""
    document = _transcript(agency_a, membership_a, paid_cycle_a)
    _deliver(document, MAX_RECEIVES, OcrUnavailable("x"))
    client.force_login(user_a)
    poll = _get(client, domain_a, f"{UPLOADS}/{document.id}").json()
    assert poll["reading"] == {"state": "DELAYED", "refusal": "", "refusal_page": None}
    assert _get(client, domain_a, "/api/documents/transcript").json()["delayed"] is True


def test_the_worker_marks_the_scan_queue_s_last_failure(monkeypatch):
    from django.core.management import call_command

    from apps.documents.management.commands import run_document_worker

    calls = []
    monkeypatch.setattr(run_document_worker.boto3, "client", lambda name: object())
    monkeypatch.setattr(run_document_worker, "consume_once", lambda **kw: calls.append(kw) or 0)
    call_command("run_document_worker", "--once")
    hooks = {call["message_type"]: call.get("on_last_failure") for call in calls}
    assert hooks == {ScanResultEvent: mark_read_failed, DocumentWorkMessage: None}
