import boto3  # type: ignore[import-untyped]
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from apps.queue import consume_once
from apps.research.dispatch import recover_undispatched_runs
from apps.research.provenance_job import Deps, check_named_program, check_pending
from apps.research.schemas import ResearchMessage
from apps.research.services import handle_research_message
from apps.research.worker import process_research_message


def _handle(message: ResearchMessage) -> None:
    handle_research_message(message)


def route(message: ResearchMessage) -> None:
    """A provenance check runs here, outside the tenant transaction
    `process_research_message` opens: it reads and writes only the shared
    catalogue, and a register load is minutes of HTTP (spec §7.1). A named
    programme's check likewise, writing its tenant copy in its own short
    transaction afterwards (§7.4). Every other message keeps its path."""
    if message.kind == "check_provenance":
        check_pending(message.body_ids, now=timezone.now(), deps=Deps())
        return
    if message.kind == "check_named_program":
        check_named_program(message)
        return
    process_research_message(message, _handle)


class Command(BaseCommand):
    help = "Consume tenant-scoped research work from SQS"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")

    def handle(self, *_args: object, **options: object) -> None:
        client = boto3.client("sqs")
        while True:
            recover_undispatched_runs(client=client, queue_url=settings.RESEARCH_QUEUE_URL)
            consume_once(
                client=client,
                queue_url=settings.RESEARCH_QUEUE_URL,
                message_type=ResearchMessage,
                handler=route,
            )
            if options["once"]:
                return
