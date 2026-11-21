"""Facts a portal asked for that the student does not hold yet (owner, 2026-10-09).

A fact-less field is the student's to type -- the red "You fill this" box -- and
never blocks the application or calls a counsellor. Such fields fill themselves
once the student's own upload is read (spec 2026-10-12): the document worker reads
every passport when it is uploaded, and this hook catches the uploads made before
that existed. It only queues: it runs inside mint_packet, in the web process, and
never calls Azure, never raises and never blocks.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import cache
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from django.conf import settings

from apps.concierge.models import DocumentVersion
from apps.documents import document_reading
from apps.documents.document_queue import DocumentWorkMessage, enqueue_document_work
from apps.documents.models import DocumentReading
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .models import Application

logger = logging.getLogger(__name__)

#: Which upload kind can supply a field (spec §7.1).
KIND_FOR_PREFIX: tuple[tuple[str, str], ...] = (
    ("identity.", "PASSPORT"),
    ("id_document.", "PASSPORT"),
    ("language.", "LANGUAGE_CERTIFICATE"),
    ("education.", "DIPLOMA"),
)
_PER_PACKET = 5

#: The hook runs inside mint_packet, in a web request: an SQS outage must cost a few
#: seconds, never the request (plan 1 final review, T8). One attempt: a QUEUED row
#: whose message never arrived is picked up by the resume sweep.
_SQS_CONFIG = Config(connect_timeout=2, read_timeout=3, retries={"total_max_attempts": 1})


@cache
def _sqs_client() -> Any:
    return boto3.client("sqs", config=_SQS_CONFIG)


def request_fact_reading(application: Application, fields: Sequence[str]) -> None:
    """Queue a reading of each unread upload that could supply one of `fields`."""
    try:
        _request(application, fields)
    except Exception as error:  # never into mint_packet
        logger.warning("FactReadingNotQueued application=%s error=%s",
                       application.id, type(error).__name__)


def _request(application: Application, fields: Sequence[str]) -> None:
    if not document_reading.enabled():
        return
    kinds = {kind for field in fields for prefix, kind in KIND_FOR_PREFIX
             if field.startswith(prefix) and document_reading.kind_enabled(kind)}
    if not kinds:
        return
    with tenant_scope(application.tenant_id), tenant_transaction(application.tenant_id):
        unread = list(
            DocumentVersion.objects.filter(
                student_id=application.student_id, kind__in=kinds, state="AVAILABLE",
                retired_at__isnull=True,
            )
            .exclude(id__in=DocumentReading.objects.values("document_id"))
            .values_list("id", "kind")[:_PER_PACKET]
        )
    for document_id, kind in unread:
        if document_reading.queue_reading(application.tenant_id, document_id):
            enqueue_document_work(
                DocumentWorkMessage(
                    action="read_document", kind=kind, tenant_id=application.tenant_id,
                    student_id=application.student_id, document_id=document_id,
                ),
                client=_sqs_client(),
                queue_url=settings.DOCUMENT_QUEUE_URL,
            )
