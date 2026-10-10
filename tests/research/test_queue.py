from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from apps.queue import consume_once
from apps.research.queue import enqueue_research
from apps.research.schemas import ResearchMessage


@pytest.mark.parametrize("kind", ["run_research", "revalidate_source"])
def test_enqueue_uses_validated_tenant_as_message_group_id(kind: str) -> None:
    client = Mock()
    tenant_id = uuid4()
    message = ResearchMessage(
        kind=kind,
        tenant_id=tenant_id,
        run_id=uuid4(),
        snapshot_id=uuid4() if kind == "revalidate_source" else None,
    )

    enqueue_research(message, client=client, queue_url="queue-url")

    kwargs = client.send_message.call_args.kwargs
    assert kwargs["MessageGroupId"] == str(tenant_id)
    assert ResearchMessage.model_validate_json(kwargs["MessageBody"]) == message


def test_message_rejects_missing_tenant() -> None:
    with pytest.raises(ValidationError):
        ResearchMessage.model_validate({"kind": "run_research", "run_id": uuid4()})


def test_consumer_deletes_only_successful_delivery() -> None:
    message = ResearchMessage(kind="run_research", tenant_id=uuid4(), run_id=uuid4())
    client = Mock()
    client.receive_message.return_value = {
        "Messages": [{"Body": message.model_dump_json(), "ReceiptHandle": "receipt"}]
    }
    handler = Mock()

    assert (
        consume_once(
            client=client, queue_url="queue-url", message_type=ResearchMessage, handler=handler
        )
        == 1
    )
    handler.assert_called_once_with(message)
    client.delete_message.assert_called_once_with(QueueUrl="queue-url", ReceiptHandle="receipt")


def test_consumer_leaves_failed_delivery_for_redrive() -> None:
    message = ResearchMessage(kind="run_research", tenant_id=uuid4(), run_id=uuid4())
    client = Mock()
    client.receive_message.return_value = {
        "Messages": [{"Body": message.model_dump_json(), "ReceiptHandle": "receipt"}]
    }
    handler = Mock(side_effect=RuntimeError("retry"))

    with pytest.raises(RuntimeError, match="retry"):
        consume_once(
            client=client, queue_url="queue-url", message_type=ResearchMessage, handler=handler
        )
    client.delete_message.assert_not_called()
