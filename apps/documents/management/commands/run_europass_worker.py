"""Drain the Europass render queue.

Runs as its OWN ECS service, pinned to one task. It is not folded into
run_research_worker because scaling that service for research throughput
would multiply this worker's request rate at europa.eu as a side effect.
"""

import time

import boto3  # type: ignore[import-untyped]
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from apps.documents.europass import EuropassUnavailable
from apps.documents.europass_queue import EuropassRenderMessage
from apps.documents.europass_render import CircuitOpen
from apps.documents.europass_worker import process_europass_message
from apps.documents.models import EuropassCircuit
from apps.queue import consume_once


class Command(BaseCommand):
    help = "Consume Europass render work from SQS, paced to a fixed rate"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")

    def handle(self, *_args: object, **options: object) -> None:
        client = boto3.client("sqs")
        while True:
            try:
                consume_once(
                    client=client,
                    queue_url=settings.EUROPASS_QUEUE_URL,
                    message_type=EuropassRenderMessage,
                    handler=process_europass_message,
                )
            except CircuitOpen:
                # A routine, designed pause -- not a crash (ruling F-I).
                # Letting this kill the process would restart the ECS task,
                # and each restart re-polls the same message, burning its
                # limited SQS redelivery budget (maxReceiveCount: 3) faster
                # than the pause elapses -- driving CVs to the DLQ for no
                # reason. Wait out what is left of the pause and try again.
                paused_until = EuropassCircuit.load().paused_until
                remaining = (paused_until - timezone.now()).total_seconds() if paused_until else 0.0
                self.stderr.write(f"Europass circuit open; waiting {max(remaining, 0):.0f}s")
                time.sleep(max(remaining, 0))
            except EuropassUnavailable as error:
                # Every other member of the family (EuropassThrottled, a
                # europa.eu 5xx, EuropassProvenanceMissing, RenderRateLimited)
                # is also a designed, expected failure mode -- not a crash.
                # The identical reasoning as the CircuitOpen branch above
                # applies: an uncaught exception here kills the ECS task,
                # each restart re-polls and burns the maxReceiveCount: 3
                # budget faster than the condition clears, and the traceback
                # would print to the log group the canary alarm also reads
                # (EuropassCanaryFailureFilter), paging someone for an
                # ordinary europa.eu outage. The message stays undeleted;
                # SQS redelivers it, same as any other left-on-the-queue
                # message.
                self.stderr.write(f"Europass render deferred: {error}")
            if options["once"]:
                return
