"""Drain both document queues.

Its own ECS service, mirroring run_europass_worker. Not folded into
run_research_worker: that service is scaled for research throughput, and this
one holds a different pair of grants.

One task drains both queues because they share a lifecycle -- an upload's
scan verdict and the generation it eventually causes are the same student's
journey, and two services would be two task definitions, two log groups and
two sets of alarms for a combined ~100 documents a day.

Both queues are always polled in one pass, even if one defers: a rate limit
on the scan queue must not suppress the work queue poll, and vice versa.

# ponytail: one worker holds both grants (quarantine/* read for the scan
# path, tenants/* write for the render path). Split the task definition if
# the scan path ever needs to run untrusted code.
"""

import boto3  # type: ignore[import-untyped]
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.documents.document_queue import DocumentWorkMessage, ScanResultEvent, consume_once
from apps.documents.document_worker import (
    handle_document_work,
    handle_scan_result,
    mark_read_failed,
)
from apps.documents.ingestion import IngestionRateLimited


class Command(BaseCommand):
    help = "Consume GuardDuty scan verdicts and document work from SQS"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")

    def handle(self, *_args: object, **options: object) -> None:
        client = boto3.client("sqs")
        while True:
            try:
                consume_once(
                    client=client,
                    queue_url=settings.DOCUMENT_SCAN_QUEUE_URL,
                    handler=handle_scan_result,
                    message_type=ScanResultEvent,
                    on_last_failure=mark_read_failed,
                )
            except IngestionRateLimited as error:
                # Our own ingestion limiter, not a crash. Same reasoning as
                # run_europass_worker's deferred branch: an uncaught exception
                # kills the ECS task, each restart re-polls the same message
                # and burns the maxReceiveCount budget faster than the window
                # rolls over.
                #
                # The scan message is not deleted, so SQS redelivers it -- and
                # for ingestion that does not eventually succeed: the window is
                # 3600s while VisibilityTimeout 900 x maxReceiveCount 3 = 2700s,
                # so the scan message exhausts its redeliveries and lands in the
                # dead-letter queue, where the depth alarm is the intended
                # signal. (CV generation rate limits are handled in
                # document_worker._generate via cv_jobs.defer instead.)
                self.stderr.write(f"Scan queue deferred: {error}")
            try:
                consume_once(
                    client=client,
                    queue_url=settings.DOCUMENT_QUEUE_URL,
                    handler=handle_document_work,
                    message_type=DocumentWorkMessage,
                )
            except IngestionRateLimited as error:
                self.stderr.write(f"Work queue deferred: {error}")
            if options["once"]:
                return
