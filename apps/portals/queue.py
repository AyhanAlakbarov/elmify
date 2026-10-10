"""Portal-side queue policy. The transport itself is apps/queue.py."""

from apps.queue import SQSClient, enqueue

from .schemas import PortalMessage

__all__ = ["SQSClient", "enqueue_portal_work"]


def enqueue_portal_work(
    message: PortalMessage, *, client: SQSClient | None = None, queue_url: str
) -> None:
    """Standard queue, no group id -- like every other queue in this template.

    Ordering needs no queue feature here: there is one portal task
    (PortalDesiredCount maxes at 1) consuming one message at a time, so two
    workers never hold one application's browser profile at once. What guards
    an SQS redelivery is the state check in handle_portal_message, not a
    group id.
    """
    enqueue(message, client=client, queue_url=queue_url)
