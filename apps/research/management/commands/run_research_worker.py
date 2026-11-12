import boto3  # type: ignore[import-untyped]
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from apps.funding.rates import latest_table
from apps.queue import consume_once
from apps.research.dispatch import recover_undispatched_runs
from apps.research.provenance_job import Deps, check_named_program, check_pending
from apps.research.schemas import ResearchMessage
from apps.research.services import handle_research_message
from apps.research.tap import run_tap
from apps.research.worker import process_research_message
from apps.tenancy.context import tenant_scope


def _handle(message: ResearchMessage) -> None:
    # The newest stored CBAR day (fetch_cbar_rates). None on the first day,
    # and the spine then publishes a pack that says so.
    handle_research_message(message, rates=latest_table())


def route(message: ResearchMessage) -> None:
    """A provenance check runs here, outside the tenant transaction
    `process_research_message` opens: it reads and writes only the shared
    catalogue, and a register load is minutes of HTTP (spec §7.1). A named
    programme's check likewise, writing its tenant copy in its own short
    transaction afterwards (§7.4). A search tap runs in its tenant's scope but
    outside any held transaction (spec 10.5). Every other message keeps its path."""
    if message.kind == "check_provenance":
        check_pending(message.body_ids, now=timezone.now(), deps=Deps())
        return
    if message.kind == "check_named_program":
        check_named_program(message)
        return
    if message.kind == "search_tap":
        # Outside process_research_message's transaction.atomic(): each wallet
        # charge commits on its own, and a failure later in the tap must not
        # roll back money already spent (apps/research/wallet.py).
        assert message.tap_id is not None  # the schema requires it for search_tap
        with tenant_scope(message.tenant_id):
            run_tap(message.tap_id, inputs=message.inputs)
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
