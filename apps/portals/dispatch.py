"""Resume applications whose human has finished.

Polled from the worker loop rather than triggered from the concierge app: a
callback there would put portal automation inside the module that
tests/concierge/test_roadmap.py pins as human-recorded facts only. This is the
same shape as apps/research/dispatch.py::recover_undispatched_runs: the select
closes its transaction before any dispatch happens, and each application is
resumed in its own short transaction, isolated by a try/except so one
application's failure can neither roll back another application's
already-sent message nor abort a sibling tenant's batch.
"""

import logging
from uuid import UUID

from django.conf import settings
from django.db import transaction

from apps.concierge.models import RoadmapItem
from apps.queue import SQSClient
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency

from .models import Application
from .queue import enqueue_portal_work
from .schemas import PortalMessage

logger = logging.getLogger(__name__)

#: The states a human closing their task can release. A missing fact and a
#: personal action release the same way a challenge does -- the fact was added
#: or the action was performed, and the item being DONE is the signal.
RESUMABLE = (
    Application.State.BLOCKED_CHALLENGE,
    Application.State.BLOCKED_MISSING_FACT,
    Application.State.BLOCKED_PERSONAL_ACTION,
    Application.State.BLOCKED_PORTAL_ERROR,
)


def resume_application(
    *,
    tenant_id: UUID,
    application_id: UUID,
    client: SQSClient | None = None,
    queue_url: str | None = None,
) -> bool:
    """One application, one short transaction. Never raises.

    The recheck under select_for_update reproduces the batch select's whole
    predicate (state, and the roadmap item still DONE), not just half of it --
    the same idempotency guard dispatch_recommendation_run gets for free
    because its select and recheck are already one field. Splitting the
    select from the dispatch widens the window for the item to move, so the
    recheck has to close it, not just the window's more likely half. A
    cleared exception_item is treated as "not still DONE": an application
    already resumed by a previous poll must not be re-enqueued.
    """
    try:
        with transaction.atomic(), tenant_scope(tenant_id):
            set_local_tenant(tenant_id)
            application = Application.objects.select_for_update().get(id=application_id)
            if application.state not in RESUMABLE or application.portal_form_id is None:
                return False
            if (
                application.exception_item is None
                or application.exception_item.state != RoadmapItem.State.DONE
            ):
                return False
            enqueue_portal_work(
                PortalMessage(
                    kind="resume_application",
                    tenant_id=tenant_id,
                    application_id=application.id,
                ),
                client=client,
                queue_url=queue_url or settings.PORTAL_QUEUE_URL,
            )
            application.state = Application.State.PREPARING
            application.exception_item = None
            application.save(update_fields=["state", "exception_item"])
    except Exception:
        logger.exception("portal resume failed for application %s", application_id)
        return False
    logger.info("PortalResume application=%s", application_id)
    return True


def resume_completed_exceptions(
    *, client: SQSClient | None = None, queue_url: str | None = None
) -> int:
    resumed = 0
    for tenant_id in Agency.objects.values_list("id", flat=True):
        with transaction.atomic(), tenant_scope(tenant_id):
            set_local_tenant(tenant_id)
            application_ids = list(
                # A portal-less application (dashboard spec §7) never reaches
                # the retiring portal worker, whose asserts rest on this.
                Application.objects.filter(
                    state__in=RESUMABLE,
                    exception_item__state=RoadmapItem.State.DONE,
                    portal_form__isnull=False,
                ).values_list("id", flat=True)
            )
        for application_id in application_ids:
            resumed += resume_application(
                tenant_id=tenant_id,
                application_id=application_id,
                client=client,
                queue_url=queue_url,
            )
    return resumed
