import json
from pathlib import Path
from uuid import uuid4

import pytest

from apps.documents.document_queue import (
    DocumentWorkMessage,
    ScanResultEvent,
    consume_once,
    enqueue_document_work,
)

FIXTURE = Path(__file__).parent / "fixtures" / "guardduty_scan_result.json"


class _FakeSQS:
    def __init__(self, messages=()):
        self.sent = []
        self.deleted = []
        self._messages = list(messages)

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {}

    def receive_message(self, **kwargs):
        return {"Messages": self._messages}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)
        return {}


def _work(**overrides):
    fields = {
        "action": "generate",
        "kind": "CV",
        "tenant_id": uuid4(),
        "student_id": uuid4(),
    }
    fields.update(overrides)
    return DocumentWorkMessage(**fields)


def _event(**detail_overrides):
    event = json.loads(FIXTURE.read_text())
    event["detail"]["scanResultDetails"].update(detail_overrides)
    return event


def test_the_work_message_carries_no_pii_fields():
    """A queue is a durable store with its own retention policy. A student's
    name or employment history must not get a second copy there under
    different rules from the first -- the worker reads content from the
    database, under tenant scope."""
    assert set(DocumentWorkMessage.model_fields) == {
        "schema_version",
        "action",
        "kind",
        "tenant_id",
        "student_id",
        "draft_id",
        "programme_id",
        "application_id",
    }


def test_a_message_written_before_programme_id_existed_still_parses():
    """The field is optional so a NEW worker can read an OLD message. The
    reverse -- an old worker reading a new message -- is impossible to fix
    here (extra="forbid"), and is handled by deploying the worker first;
    scripts/deploy.sh pins that order."""
    older = '{"schema_version":1,"action":"generate","kind":"CV",' + (
        f'"tenant_id":"{uuid4()}","student_id":"{uuid4()}"' + "}"
    )
    assert DocumentWorkMessage.model_validate_json(older).programme_id is None


def test_the_work_message_rejects_extra_fields():
    with pytest.raises(ValueError):
        _work(full_name="Jane Doe")


def test_the_work_message_rejects_an_unknown_action():
    with pytest.raises(ValueError):
        _work(action="delete")


def test_enqueue_sends_the_serialised_message_without_a_group_id():
    """Standard queue, not FIFO: MessageGroupId is FIFO-only and SQS rejects
    it on a standard queue."""
    client = _FakeSQS()
    message = _work()

    enqueue_document_work(message, client=client, queue_url="q")

    body = json.loads(client.sent[0]["MessageBody"])
    assert body["student_id"] == str(message.student_id)
    assert client.sent[0]["QueueUrl"] == "q"
    assert "MessageGroupId" not in client.sent[0]


def test_consume_once_invokes_the_handler_and_deletes():
    message = _work()
    client = _FakeSQS([{"Body": message.model_dump_json(), "ReceiptHandle": "rh-1"}])
    seen = []

    count = consume_once(
        client=client, queue_url="q", handler=seen.append, message_type=DocumentWorkMessage
    )

    assert count == 1
    assert seen[0].student_id == message.student_id
    assert client.deleted[0]["ReceiptHandle"] == "rh-1"


def test_a_malformed_raw_message_is_skipped_and_not_counted():
    good = _work()
    client = _FakeSQS(
        [
            {"Body": 12345, "ReceiptHandle": "rh-bad"},
            {"Body": good.model_dump_json(), "ReceiptHandle": "rh-good"},
        ]
    )
    seen = []

    count = consume_once(
        client=client, queue_url="q", handler=seen.append, message_type=DocumentWorkMessage
    )

    assert count == 1
    assert client.deleted == [{"QueueUrl": "q", "ReceiptHandle": "rh-good"}]


def test_a_failing_handler_does_not_delete_the_message():
    """The message must return to the queue so SQS can retry it. Deleting on
    failure silently loses a student's CV."""
    client = _FakeSQS([{"Body": _work().model_dump_json(), "ReceiptHandle": "rh-2"}])

    def _boom(_message):
        raise RuntimeError("handler failed")

    with pytest.raises(RuntimeError):
        consume_once(
            client=client, queue_url="q", handler=_boom, message_type=DocumentWorkMessage
        )
    assert client.deleted == []


@pytest.mark.parametrize(
    "status",
    ["NO_THREATS_FOUND", "THREATS_FOUND", "UNSUPPORTED", "ACCESS_DENIED", "FAILED"],
)
def test_the_scan_event_parses_every_documented_status(status):
    """AWS publishes a verbatim sample per scanResultStatus. All five reach
    the handler as the same three values."""
    parsed = ScanResultEvent.model_validate(_event(scanResultStatus=status))

    assert parsed.scan_result == status
    assert parsed.object_key.startswith("quarantine/")
    assert parsed.bucket_name == "test-evidence-bucket"


def test_the_scan_event_reads_scan_result_status_not_scan_status():
    """detail.scanStatus is a DIFFERENT field with a different vocabulary
    (COMPLETED/SKIPPED/FAILED): whether the scan ran, not what it found.
    Reading it would collapse 'password-protected' and 'access denied' into
    one indistinguishable state."""
    event = _event(scanResultStatus="THREATS_FOUND")
    event["detail"]["scanStatus"] = "COMPLETED"

    assert ScanResultEvent.model_validate(event).scan_result == "THREATS_FOUND"


def test_the_scan_event_tolerates_populated_threat_fields():
    """threats and statusReasons are null on a clean scan and populated on
    THREATS_FOUND / UNSUPPORTED / ACCESS_DENIED. Neither is read, and neither
    may break parsing."""
    event = _event(
        scanResultStatus="THREATS_FOUND",
        threats=[{"name": "EICAR-Test-File"}],
        statusReasons=["reason"],
    )

    assert ScanResultEvent.model_validate(event).scan_result == "THREATS_FOUND"


def test_the_scan_event_keeps_the_version_that_was_scanned():
    """The bucket is versioned and the upload form stays valid for 900 s: the scanned
    version, not the key, is what was judged clean."""
    assert ScanResultEvent.model_validate(_event()).version_id == (
        "d41d8cd98f00b204e9800998eEXAMPLE"
    )
    event = json.loads(FIXTURE.read_text())
    del event["detail"]["s3ObjectDetails"]["versionId"]
    # Parsed, so a THREATS_FOUND verdict is still recorded; never promoted (the worker).
    assert ScanResultEvent.model_validate(event).version_id is None


def test_an_empty_version_is_no_version_and_never_stops_a_verdict_being_read():
    """An empty versionId must not fail validation: a THREATS_FOUND would then never be
    recorded and the upload would sit QUARANTINED instead of BLOCKED."""
    event = _event(scanResultStatus="THREATS_FOUND")
    event["detail"]["s3ObjectDetails"]["versionId"] = ""
    parsed = ScanResultEvent.model_validate(event)
    assert (parsed.scan_result, parsed.version_id) == ("THREATS_FOUND", None)


def test_an_event_missing_the_object_details_is_rejected():
    event = json.loads(FIXTURE.read_text())
    del event["detail"]["s3ObjectDetails"]

    with pytest.raises(ValueError):
        ScanResultEvent.model_validate(event)


@pytest.mark.parametrize(
    "malformed_value",
    [
        "not-a-dict",  # string
        123,  # int
        ["a", "list"],  # list
        None,  # None
    ],
)
def test_malformed_detail_becomes_validation_error_not_attribute_error(malformed_value):
    """A malformed event must be a rejected message, not a crashed consumer.
    If the validator raises AttributeError instead of ValidationError, SQS
    redelivers the message forever and the queue wedges behind it. The
    validator guards all intermediate lookups with isinstance checks so every
    non-dict path degrades to {} and therefore to a None-valued required
    field, becoming a ValidationError instead of an AttributeError crash."""
    event = json.loads(FIXTURE.read_text())
    event["detail"] = malformed_value

    with pytest.raises(ValueError):
        ScanResultEvent.model_validate(event)


@pytest.mark.parametrize(
    "malformed_value",
    [
        "not-a-dict",  # string
        123,  # int
        ["a", "list"],  # list
        None,  # None
    ],
)
def test_malformed_s3_object_details_becomes_validation_error_not_attribute_error(
    malformed_value,
):
    """A malformed event must be a rejected message, not a crashed consumer.
    If the validator raises AttributeError instead of ValidationError, SQS
    redelivers the message forever and the queue wedges behind it. The
    validator guards all intermediate lookups with isinstance checks so every
    non-dict path degrades to {} and therefore to a None-valued required
    field, becoming a ValidationError instead of an AttributeError crash."""
    event = json.loads(FIXTURE.read_text())
    event["detail"]["s3ObjectDetails"] = malformed_value

    with pytest.raises(ValueError):
        ScanResultEvent.model_validate(event)


@pytest.mark.parametrize(
    "malformed_value",
    [
        "not-a-dict",  # string
        123,  # int
        ["a", "list"],  # list
        None,  # None
    ],
)
def test_malformed_scan_result_details_becomes_validation_error_not_attribute_error(
    malformed_value,
):
    """A malformed event must be a rejected message, not a crashed consumer.
    If the validator raises AttributeError instead of ValidationError, SQS
    redelivers the message forever and the queue wedges behind it. The
    validator guards all intermediate lookups with isinstance checks so every
    non-dict path degrades to {} and therefore to a None-valued required
    field, becoming a ValidationError instead of an AttributeError crash."""
    event = json.loads(FIXTURE.read_text())
    event["detail"]["scanResultDetails"] = malformed_value

    with pytest.raises(ValueError):
        ScanResultEvent.model_validate(event)
