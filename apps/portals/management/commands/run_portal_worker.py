import boto3  # type: ignore[import-untyped]
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.portals.dispatch import resume_completed_exceptions
from apps.portals.profiles import sweep_expired
from apps.portals.schemas import PortalMessage
from apps.portals.worker import handle_portal_message, process_portal_message
from apps.queue import consume_once


class Command(BaseCommand):
    help = "Consume tenant-scoped portal work from SQS"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")

    def handle(self, *_args: object, **options: object) -> None:
        client = boto3.client("sqs")

        while True:
            # Before receiving, not after: a worker that dies mid-loop has
            # still swept, and a profile past its TTL should not survive
            # because the queue happened to be busy.
            sweep_expired()
            resume_completed_exceptions(client=client)
            consume_once(
                client=client,
                queue_url=settings.PORTAL_QUEUE_URL,
                message_type=PortalMessage,
                handler=lambda message: process_portal_message(message, handle_portal_message),
            )
            if options["once"]:
                return
