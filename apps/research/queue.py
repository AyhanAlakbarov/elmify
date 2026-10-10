"""Research-side queue policy. The transport itself is apps/queue.py."""

from apps.queue import SQSClient, enqueue

from .schemas import ResearchMessage

__all__ = ["SQSClient", "enqueue_research"]


def enqueue_research(
    message: ResearchMessage, *, client: SQSClient | None = None, queue_url: str
) -> None:
    """FIFO, grouped by tenant: one tenant's runs never overtake each other,
    and one tenant's backlog never blocks another's."""
    enqueue(message, client=client, queue_url=queue_url, group_id=str(message.tenant_id))
