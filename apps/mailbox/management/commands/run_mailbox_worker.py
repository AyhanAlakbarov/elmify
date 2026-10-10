"""Drain the mailbox queue: one Graph notification, one sync.

Its OWN ECS service, one task, like the Europass worker: the web tier answers
Graph within three seconds by only enqueueing (apps/mailbox/push.py), and this
is where the sync that may take tens of seconds actually runs. handle_work
never raises for a provider or a limit, so a Graph outage does not walk
messages into the dead-letter queue; what it does not read, the six-hourly
sweep does.
"""

import boto3  # type: ignore[import-untyped]
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.mailbox.push import MailboxWork, handle_work
from apps.queue import consume_once


class Command(BaseCommand):
    help = "Consume mailbox push work from SQS"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")

    def handle(self, *_args: object, **options: object) -> None:
        client = boto3.client("sqs")
        while True:
            consume_once(
                client=client,
                queue_url=settings.MAILBOX_QUEUE_URL,
                message_type=MailboxWork,
                handler=handle_work,
            )
            if options["once"]:
                return
