"""The shared transport. Per-app behaviour stays in each app's own test module."""

from typing import Literal
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from apps.queue import consume_once, enqueue


class Fixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    tenant_id: UUID


def test_enqueue_omits_the_group_id_for_a_standard_queue():
    """A MessageGroupId on a standard queue is an InvalidParameterValue from
    SQS, so the parameter is absent rather than empty."""
    client = Mock()

    enqueue(Fixture(tenant_id=uuid4()), client=client, queue_url="q")

    assert "MessageGroupId" not in client.send_message.call_args.kwargs


def test_enqueue_sets_the_group_id_when_one_is_given():
    client = Mock()
    tenant_id = uuid4()

    enqueue(Fixture(tenant_id=tenant_id), client=client, queue_url="q", group_id=str(tenant_id))

    assert client.send_message.call_args.kwargs["MessageGroupId"] == str(tenant_id)


def test_consume_validates_against_the_type_the_caller_named():
    """The whole point of the parameter: a portal message arriving on the
    research queue must fail validation, not be handed to a research handler
    that reads attributes it does not have."""
    client = Mock()
    client.receive_message.return_value = {
        "Messages": [{"Body": '{"schema_version": 1, "unexpected": true}', "ReceiptHandle": "r"}]
    }

    with pytest.raises(ValidationError):
        consume_once(client=client, queue_url="q", message_type=Fixture, handler=Mock())
    client.delete_message.assert_not_called()


def test_consume_counts_what_it_processed_not_what_it_received():
    """A malformed envelope is skipped, not counted -- a caller that logs the
    return value as throughput would otherwise report work never done."""
    message = Fixture(tenant_id=uuid4())
    client = Mock()
    client.receive_message.return_value = {
        "Messages": [
            {"Body": message.model_dump_json(), "ReceiptHandle": "r"},
            {"NoBody": True},
        ]
    }
    seen = []

    result = consume_once(client=client, queue_url="q", message_type=Fixture, handler=seen.append)

    assert result == 1
    assert seen == [message]


def _boom(_message):
    raise RuntimeError("handler failed")


def test_on_last_failure_fires_on_the_delivery_that_hits_max_receives():
    message = Fixture(tenant_id=uuid4())
    client = Mock()
    client.receive_message.return_value = {
        "Messages": [
            {
                "Body": message.model_dump_json(),
                "ReceiptHandle": "r",
                "Attributes": {"ApproximateReceiveCount": "3"},
            }
        ]
    }
    seen = []

    with pytest.raises(RuntimeError):
        consume_once(
            client=client,
            queue_url="q",
            message_type=Fixture,
            handler=_boom,
            on_last_failure=seen.append,
            max_receives=3,
        )

    assert seen == [message]
    client.delete_message.assert_not_called()


def test_on_last_failure_does_not_fire_before_the_final_delivery():
    """Earlier failures still retry -- on_last_failure marks a terminal state
    only on the delivery SQS will not repeat."""
    message = Fixture(tenant_id=uuid4())
    client = Mock()
    client.receive_message.return_value = {
        "Messages": [
            {
                "Body": message.model_dump_json(),
                "ReceiptHandle": "r",
                "Attributes": {"ApproximateReceiveCount": "1"},
            }
        ]
    }
    seen = []

    with pytest.raises(RuntimeError):
        consume_once(
            client=client,
            queue_url="q",
            message_type=Fixture,
            handler=_boom,
            on_last_failure=seen.append,
            max_receives=3,
        )

    assert seen == []


def test_on_last_failure_is_never_called_without_max_receives():
    """A caller that passes on_last_failure but forgets max_receives gets no
    terminal-state write rather than one that fires on every delivery."""
    message = Fixture(tenant_id=uuid4())
    client = Mock()
    client.receive_message.return_value = {
        "Messages": [{"Body": message.model_dump_json(), "ReceiptHandle": "r"}]
    }
    seen = []

    with pytest.raises(RuntimeError):
        consume_once(
            client=client,
            queue_url="q",
            message_type=Fixture,
            handler=_boom,
            on_last_failure=seen.append,
        )

    assert seen == []
