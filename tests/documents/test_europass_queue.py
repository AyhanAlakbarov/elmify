import json
from uuid import uuid4

import pytest

from apps.documents.europass_queue import EuropassRenderMessage, enqueue_europass_render
from apps.queue import consume_once


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


def _message():
    return EuropassRenderMessage(tenant_id=uuid4(), draft_id=uuid4())


def test_the_message_carries_no_pii_fields():
    """Pins a privacy decision. A queue is a durable store with its own
    retention; a student's employment history must not get a second copy
    there with different rules from the first."""
    fields = set(EuropassRenderMessage.model_fields)
    assert fields == {"schema_version", "tenant_id", "draft_id"}


def test_the_message_rejects_extra_fields():
    with pytest.raises(ValueError):
        EuropassRenderMessage(tenant_id=uuid4(), draft_id=uuid4(), full_name="Jane Doe")


def test_enqueue_sends_the_serialised_message():
    client = _FakeSQS()
    message = _message()
    enqueue_europass_render(message, client=client, queue_url="q")
    body = json.loads(client.sent[0]["MessageBody"])
    assert body["draft_id"] == str(message.draft_id)
    assert client.sent[0]["QueueUrl"] == "q"


def test_enqueue_does_not_send_a_message_group_id():
    """This is a standard queue, not FIFO. MessageGroupId is a FIFO-only
    parameter and SQS rejects it on a standard queue."""
    client = _FakeSQS()
    enqueue_europass_render(_message(), client=client, queue_url="q")
    assert "MessageGroupId" not in client.sent[0]


def test_consume_once_invokes_the_handler_and_deletes():
    message = _message()
    client = _FakeSQS([{"Body": message.model_dump_json(), "ReceiptHandle": "rh-1"}])
    seen = []
    count = consume_once(
        client=client, queue_url="q", message_type=EuropassRenderMessage, handler=seen.append
    )
    assert count == 1
    assert seen[0].draft_id == message.draft_id
    assert client.deleted[0]["ReceiptHandle"] == "rh-1"


def test_a_malformed_message_is_skipped_and_excluded_from_the_count():
    """Ruling F-E: consume_once's isinstance guards `continue` past a message
    they never processed, but it used to return len(messages) regardless --
    a lying -> int contract. A malformed raw message must be neither deleted
    nor counted."""
    good = _message()
    client = _FakeSQS(
        [
            {"Body": 12345, "ReceiptHandle": "rh-bad"},
            {"Body": good.model_dump_json(), "ReceiptHandle": "rh-good"},
        ]
    )
    seen = []
    count = consume_once(
        client=client, queue_url="q", message_type=EuropassRenderMessage, handler=seen.append
    )
    assert count == 1
    assert [m.draft_id for m in seen] == [good.draft_id]
    assert client.deleted == [{"QueueUrl": "q", "ReceiptHandle": "rh-good"}]


def test_a_failing_handler_does_not_delete_the_message():
    """The message must return to the queue so SQS can retry it. Deleting on
    failure silently loses a student's CV."""
    message = _message()
    client = _FakeSQS([{"Body": message.model_dump_json(), "ReceiptHandle": "rh-2"}])

    def _boom(_message):
        raise RuntimeError("handler failed")

    with pytest.raises(RuntimeError):
        consume_once(
            client=client, queue_url="q", message_type=EuropassRenderMessage, handler=_boom
        )
    assert client.deleted == []
