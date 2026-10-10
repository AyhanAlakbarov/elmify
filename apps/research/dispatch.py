import logging
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.funding.models import RecommendationRun
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency

from .queue import SQSClient, enqueue_research
from .schemas import ResearchMessage

logger = logging.getLogger(__name__)


def dispatch_recommendation_run(
    *,
    tenant_id: UUID,
    run_id: UUID,
    client: SQSClient | None = None,
    queue_url: str | None = None,
) -> bool:
    try:
        with transaction.atomic(), tenant_scope(tenant_id):
            set_local_tenant(tenant_id)
            run = RecommendationRun.objects.select_for_update().get(id=run_id)
            if run.dispatched_at is not None:
                return False
            message = ResearchMessage(kind="run_research", tenant_id=tenant_id, run_id=run.id)
            enqueue_research(
                message,
                client=client,
                queue_url=queue_url or settings.RESEARCH_QUEUE_URL,
            )
            run.dispatched_at = timezone.now()
            run.save(update_fields=["dispatched_at"])
    except Exception:
        logger.exception("research dispatch failed for run %s", run_id)
        return False
    return True


def recover_undispatched_runs(
    *, client: SQSClient | None = None, queue_url: str | None = None
) -> int:
    delivered = 0
    for tenant_id in Agency.objects.values_list("id", flat=True):
        with transaction.atomic(), tenant_scope(tenant_id):
            set_local_tenant(tenant_id)
            run_ids = list(
                RecommendationRun.objects.filter(dispatched_at__isnull=True).values_list(
                    "id", flat=True
                )
            )
        for run_id in run_ids:
            delivered += dispatch_recommendation_run(
                tenant_id=tenant_id, run_id=run_id, client=client, queue_url=queue_url
            )
    return delivered
