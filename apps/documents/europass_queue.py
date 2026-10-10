"""SQS transport for Europass render work.

The transport itself is apps/queue.py. This module keeps only the
Europass-specific message model and its enqueue wrapper.

Unlike the research queue this one is STANDARD, not FIFO. There is exactly
one worker, so ordering is meaningless, and a standard queue has no
throughput ceiling to reason about.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from apps.queue import SQSClient, enqueue


class EuropassRenderMessage(BaseModel):
    """Identifiers only -- never content.

    A queue is a durable store with its own retention policy. Putting a
    student's name or employment history here would create a second copy of
    their personal data governed by different rules from the first, so the
    worker reads the content from the database instead, under tenant scope.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    tenant_id: UUID
    draft_id: UUID


def enqueue_europass_render(
    message: EuropassRenderMessage, *, client: SQSClient | None = None, queue_url: str
) -> None:
    """Standard queue, so no group: there is exactly one worker and ordering is
    meaningless."""
    enqueue(message, client=client, queue_url=queue_url)
