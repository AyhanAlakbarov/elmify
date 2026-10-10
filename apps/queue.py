"""One SQS transport, parameterised over the message model.

apps/research/queue.py and apps/documents/europass_queue.py were the same
sixty lines twice, differing only in the model they validated and whether the
queue was FIFO. Both now import from here. Each app keeps its own message model
and its own enqueue wrapper, because the group-id policy is the only thing that
genuinely differs between them: research groups by tenant, and Europass and
portals have no groups at all -- apps/portals/queue.py explains why the portal
queue deliberately sends no group id.
"""

from collections.abc import Callable
from typing import Any, Protocol

import boto3  # type: ignore[import-untyped]
from pydantic import BaseModel


class SQSClient(Protocol):
    def send_message(self, **kwargs: str) -> object: ...

    def receive_message(self, **kwargs: object) -> dict[str, object]: ...

    def delete_message(self, **kwargs: str) -> object: ...


def enqueue(
    message: BaseModel,
    *,
    client: SQSClient | None = None,
    queue_url: str,
    group_id: str | None = None,
) -> None:
    sqs = client or boto3.client("sqs")
    kwargs: dict[str, Any] = {"QueueUrl": queue_url, "MessageBody": message.model_dump_json()}
    # Omitted rather than sent empty. MessageGroupId is a FIFO-queue
    # parameter; enqueue_research passes one today against a queue the
    # template defines as standard (infra/template.yaml::ResearchQueue), which
    # is a pre-existing question this refactor deliberately preserves rather
    # than changes -- behaviour parity is what makes the research tests a valid
    # guard on it.
    if group_id is not None:
        kwargs["MessageGroupId"] = group_id
    sqs.send_message(**kwargs)


def consume_once[MessageT: BaseModel](
    *,
    client: SQSClient,
    queue_url: str,
    message_type: type[MessageT],
    handler: Callable[[MessageT], None],
    on_last_failure: Callable[[MessageT], None] | None = None,
    max_receives: int | None = None,
) -> int:
    """Receive at most one message, hand it to ``handler``, delete on success.

    Deletion happens only after the handler returns. A handler that raises
    leaves the message on the queue, so SQS redelivers it and the DLQ
    eventually catches what never succeeds -- that is the entire retry story.

    ``on_last_failure`` runs when the handler raises on the delivery SQS will
    not repeat (``max_receives``, the caller's own queue's ``maxReceiveCount``),
    so a failure a student is waiting on leaves a terminal state before the
    message goes where nothing reads it. The error still propagates -- this
    never replaces the dead-letter queue, only records the terminal state the
    caller cares about before the message goes there.
    """
    response = client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=20,
        AttributeNames=["ApproximateReceiveCount"],
    )
    messages = response.get("Messages", [])
    if not isinstance(messages, list):
        return 0
    processed = 0
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        body = raw.get("Body")
        receipt = raw.get("ReceiptHandle")
        if not isinstance(body, str) or not isinstance(receipt, str):
            continue
        message = message_type.model_validate_json(body)
        try:
            handler(message)
        except Exception:
            if (
                on_last_failure is not None
                and max_receives is not None
                and _receives(raw) >= max_receives
            ):
                on_last_failure(message)
            raise
        client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
        processed += 1
    return processed


def _receives(raw: dict[str, object]) -> int:
    """How many times SQS has delivered this message; 1 when it did not say, so a missing
    attribute retries rather than failing a reading early."""
    attributes = raw.get("Attributes")
    count = attributes.get("ApproximateReceiveCount") if isinstance(attributes, dict) else None
    return int(count) if isinstance(count, str) and count.isdigit() else 1
