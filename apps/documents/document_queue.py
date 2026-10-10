"""SQS transport for the document engine: our own work, and GuardDuty's verdict.

Two queues, one module. DocumentQueue carries messages we wrote;
DocumentScanQueue carries EventBridge envelopes AWS wrote. The envelope is a
second Pydantic model here rather than a second module -- they share one
consume_once, and splitting them would be two files that import each other.

DocumentWorkMessage carries identifiers only, never content, for the same
reason EuropassRenderMessage does: a queue is a durable store with its own
retention policy, so a second copy of a student's personal data must not live
there governed by different rules from the first. The worker reads the content
from the database, under tenant scope.

The transport itself is apps.queue's shared consume_once/SQSClient (also used
by apps/research/queue.py and apps/documents/europass_queue.py); this module
only adds its own message shapes and passes MAX_RECEIVES through
on_last_failure/max_receives for the scan queue's dead-letter alarm.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.queue import SQSClient, enqueue
from apps.queue import consume_once as _consume_once

__all__ = [
    "SQSClient",
    "MAX_RECEIVES",
    "DocumentWorkMessage",
    "ScanResultEvent",
    "enqueue_document_work",
    "consume_once",
]

#: DocumentScanQueue's maxReceiveCount (infra/template.yaml, pinned by tests/infra): the delivery
#: after which SQS dead-letters a message rather than handing it to a worker again.
MAX_RECEIVES = 3


class DocumentWorkMessage(BaseModel):
    """One unit of document work. Identifiers only -- see the module docstring.

    ``kind`` rather than a CV-named message: the motivation-letter engine adds
    a branch in the worker, not a queue, a task definition or an alarm. The
    accepted set of kinds is validated in exactly one place, ``api._SUPPORTED_KINDS``.

    ``draft_id`` is set for ``render`` and absent for ``generate`` -- a
    generation has no draft yet, which is the whole reason it is being queued.

    ``programme_id`` is the one thing that makes a CV tailored rather than
    generic. An id, not a Program: it names a row in the SHARED catalog, which
    every tenant reads, so it is neither PII nor tenant-scoped and the worker
    loads it itself. Optional, so a NEW worker parses an OLD message. The
    reverse is impossible here -- ``extra="forbid"`` means an OLD worker
    rejects this field and the message dead-letters -- which is why
    ``scripts/deploy.sh`` rolls the worker before the web tier, pinned by
    ``tests/infra/test_template.py``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    action: Literal["generate", "render", "capture_requirements"]
    kind: str
    tenant_id: UUID
    student_id: UUID
    draft_id: UUID | None = None
    programme_id: UUID | None = None
    #: capture_requirements only: the Application whose kit copy to write.
    application_id: UUID | None = None


class ScanResultEvent(BaseModel):
    """The three values we read out of a GuardDuty object-scan event.

    Verified against AWS's published samples (docs.aws.amazon.com/guardduty/
    latest/ug/monitor-with-eventbridge-s3-malware-protection.html), which
    publishes a verbatim sample for each of the five scanResultStatus values.

    ``scan_result`` comes from ``detail.scanResultDetails.scanResultStatus``
    and NEVER from ``detail.scanStatus``: that is a different field with a
    different vocabulary (COMPLETED / SKIPPED / FAILED) describing whether the
    scan ran rather than what it found, and reading it collapses
    "password-protected file" and "access denied" into one state.

    ``threats`` and ``statusReasons`` are null on a clean scan and populated
    otherwise. Neither is read here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_key: str
    scan_result: str
    bucket_name: str
    #: ``detail.s3ObjectDetails.versionId``: the version GuardDuty scanned. EvidenceBucket is
    #: versioned and the upload form stays valid for 900 s, so the key alone can name bytes
    #: nobody scanned. Optional so a verdict without it is still recorded (a THREATS_FOUND
    #: must block); the worker never promotes an upload whose verdict named no version.
    version_id: str | None = Field(default=None, min_length=1, max_length=1024)

    @field_validator("version_id", mode="before")
    @classmethod
    def _empty_is_none(cls, value: Any) -> Any:
        # An empty versionId says nothing about which version was scanned. As None it is
        # recorded like a missing one: never promoted, but a THREATS_FOUND still blocks.
        return None if value == "" else value

    @model_validator(mode="before")
    @classmethod
    def _unwrap_eventbridge(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "detail" not in value:
            return value
        detail = value.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        objects = detail.get("s3ObjectDetails")
        objects = objects if isinstance(objects, dict) else {}
        results = detail.get("scanResultDetails")
        results = results if isinstance(results, dict) else {}
        # Guard each intermediate lookup with an isinstance check so every
        # non-dict value degrades to {} and therefore to a None-valued required
        # field, becoming a ValidationError. This ensures no path through this
        # validator raises anything but ValidationError -- missing paths,
        # null paths, and wrong-type paths all become validation failures
        # rather than AttributeError crashes, so the worker rejects malformed
        # messages instead of dying, and SQS doesn't wedge on a message that
        # redelivers forever.
        return {
            "object_key": objects.get("objectKey"),
            "scan_result": results.get("scanResultStatus"),
            "bucket_name": objects.get("bucketName"),
            "version_id": objects.get("versionId"),
        }


def enqueue_document_work(
    message: DocumentWorkMessage, *, client: SQSClient | None = None, queue_url: str
) -> None:
    enqueue(message, client=client, queue_url=queue_url)


def consume_once[M: BaseModel](
    *,
    client: SQSClient,
    queue_url: str,
    handler: Callable[[M], None],
    message_type: type[M],
    on_last_failure: Callable[[M], None] | None = None,
) -> int:
    """apps.queue's shared consume_once, pinned to this module's own dead-letter threshold.

    ``max_receives=MAX_RECEIVES`` is DocumentScanQueue's ``maxReceiveCount``: the delivery
    on which SQS stops retrying and hands the message to the DLQ, which is also the delivery
    ``on_last_failure`` (``mark_read_failed``) must fire on.
    """
    return _consume_once(
        client=client,
        queue_url=queue_url,
        handler=handler,
        message_type=message_type,
        on_last_failure=on_last_failure,
        max_receives=MAX_RECEIVES,
    )
