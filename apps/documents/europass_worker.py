"""Process one Europass render message under tenant scope, then pace.

The delay here IS the rate limiter. Outbound rate is
``worker_tasks x (60 / delay)``, so it is a property of the deployment
rather than a counter that can drift from what the code intends. The
corollary is in infra/template.yaml: this worker's task count is a rate
knob, not a throughput knob, and must never be autoscaled.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from django.db import transaction

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant

from .europass_queue import EuropassRenderMessage
from .europass_render import CircuitOpen, render_and_store
from .models import DocumentDraft
from .render import RenderRateLimited

#: 2 seconds => a ceiling of 30 requests/minute from one task. Expected volume
#: is ~100 renders/day -- roughly 0.2/minute across a working day -- so the
#: ceiling is ~145x headroom and even a single-burst day drains in about 3.5
#: minutes. The delay is therefore not sized against demand; it is a courtesy
#: floor for a public European Commission service.
#: Turn this UP if europa.eu asks. Never down for our own convenience.
_INTER_CALL_DELAY_SECONDS = 2

logger = logging.getLogger(__name__)


def process_europass_message(
    message: EuropassRenderMessage, *, sleep: Callable[[int], None] = time.sleep
) -> None:
    with tenant_scope(message.tenant_id):
        # Short and tenant-scoped ONLY: set_local_tenant's SET LOCAL needs an
        # open transaction, but nothing below may share one with the
        # outbound europa.eu call. render_and_store's own breaker writes
        # (EuropassCircuit -- global, not tenant data) must survive on their
        # own regardless of whether this fetch, or any other tenant-scoped
        # work, ever commits (ruling F-G).
        with transaction.atomic():
            set_local_tenant(message.tenant_id)
            draft = DocumentDraft.objects.get(id=message.draft_id)

        try:
            outcome = render_and_store(draft=draft)
        except (CircuitOpen, RenderRateLimited):
            # No call reached europa.eu -- nothing to pace (ruling F-H).
            raise
        except Exception:
            # Every other exception means a call was attempted (or we cannot
            # prove otherwise) and it cost europa.eu a request. Default to
            # pacing: under-sleeping is the exact failure this worker exists
            # to prevent; over-sleeping when nothing was actually sent is
            # merely wasted time, not a correctness problem (ruling F-H).
            sleep(_INTER_CALL_DELAY_SECONDS)
            raise

    if outcome.called_remote:
        # One line per real call. A CloudWatch metric filter turns these into
        # EuropassCallsTotal (infra Task 6) -- no put_metric_data code, which
        # is how this repo already produces its other custom metrics. This is
        # the number that makes our volume answerable to europa.eu.
        logger.info("EuropassCallMade draft=%s", message.draft_id)
        # Pace only actual calls: a cache hit costs europa.eu nothing, and
        # sleeping on it would throttle the queue for no reason.
        sleep(_INTER_CALL_DELAY_SECONDS)
